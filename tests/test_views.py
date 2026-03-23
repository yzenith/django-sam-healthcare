"""
Integration tests for example/ views.
Uses Django TestClient — hits the real DB (SQLite in test).
"""
import io
import json
import os
import pytest
from django.test import TestCase, Client
from django.urls import reverse

from example.models import HL7MessageLog, PatientRecord, PatientImportRun

ADT_A01 = (
    "MSH|^~\\&|MIRTH|HOSPITAL|RECV|FAC|202512181200||ADT^A01|MSG00001|P|2.3\n"
    "PID|1||12345^^^MRN||DOE^JOHN||19800101|M|||123 MAIN ST^^ALLEN^TX^75013\n"
    "PV1|1|I|W^101^1\n"
)

ORU_R01 = (
    "MSH|^~\\&|LAB|HOSP|REC|FAC|20251218120000||ORU^R01|MSG00002|P|2.3\n"
    "PID|||67890^^^MRN||SMITH^JANE||19900215|F\n"
    "OBR|1||LAB001|58410-2^CBC WITH DIFFERENTIAL\n"
    "OBX|1|NM|718-7^Hemoglobin||13.5|g/dL|12.0-16.0|N\n"
)

MIRTH_JWT_SECRET = os.environ.get("MIRTH_JWT_SECRET", "MIRTH_DEMO_SECRET_KEY")


def _make_jwt(secret=MIRTH_JWT_SECRET, expired=False, bad_iss=False):
    import jwt, time
    payload = {
        "sub": "mirth-channel",
        "iss": "bad-issuer" if bad_iss else "django-sam-healthcare",
        "aud": "mirth-connector",
        "exp": int(time.time()) + (-10 if expired else 3600),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


# ---------------------------------------------------------------------------
# HL7TransformView  POST /api/transform/
# ---------------------------------------------------------------------------

class HL7TransformViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("hl7-transform")

    def test_adt_transform_returns_200(self):
        resp = self.client.post(
            self.url,
            data=json.dumps({"hl7_message": ADT_A01}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

    def test_adt_transform_returns_patient(self):
        resp = self.client.post(
            self.url,
            data=json.dumps({"hl7_message": ADT_A01}),
            content_type="application/json",
        )
        body = resp.json()
        self.assertIn("patient", body)
        self.assertEqual(body["patient"]["resourceType"], "Patient")

    def test_adt_transform_returns_x12(self):
        resp = self.client.post(
            self.url,
            data=json.dumps({"hl7_message": ADT_A01}),
            content_type="application/json",
        )
        body = resp.json()
        self.assertIn("x12_837", body)
        self.assertIn("CLM*", body["x12_837"])

    def test_oru_transform_returns_report(self):
        resp = self.client.post(
            self.url,
            data=json.dumps({"hl7_message": ORU_R01}),
            content_type="application/json",
        )
        body = resp.json()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("report", body)

    def test_missing_body_returns_400(self):
        resp = self.client.post(
            self.url,
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_non_hl7_body_returns_400(self):
        resp = self.client.post(
            self.url,
            data=json.dumps({"hl7_message": "NOT_AN_HL7_MESSAGE"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_raw_body_fallback(self):
        """Plain-text HL7 body (non-JSON content type) is also accepted."""
        resp = self.client.post(
            self.url,
            data=ADT_A01,
            content_type="text/plain",
        )
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# MirthHL7View  POST /api/mirth/hl7/
# ---------------------------------------------------------------------------

class MirthHL7ViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("mirth-hl7")

    def _auth_header(self, token=None):
        if token is None:
            token = _make_jwt()
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_no_auth_returns_403(self):
        resp = self.client.post(self.url, data=json.dumps({"hl7_message": ADT_A01}), content_type="application/json")
        self.assertEqual(resp.status_code, 403)

    def test_expired_jwt_returns_403(self):
        token = _make_jwt(expired=True)
        resp = self.client.post(
            self.url,
            data=json.dumps({"hl7_message": ADT_A01}),
            content_type="application/json",
            **self._auth_header(token),
        )
        self.assertEqual(resp.status_code, 403)

    def test_bad_issuer_returns_403(self):
        token = _make_jwt(bad_iss=True)
        resp = self.client.post(
            self.url,
            data=json.dumps({"hl7_message": ADT_A01}),
            content_type="application/json",
            **self._auth_header(token),
        )
        self.assertEqual(resp.status_code, 403)

    def test_valid_adt_returns_200(self):
        resp = self.client.post(
            self.url,
            data=json.dumps({"hl7_message": ADT_A01}),
            content_type="application/json",
            **self._auth_header(),
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertIn("trace_id", body)

    def test_valid_adt_creates_log_record(self):
        before = HL7MessageLog.objects.count()
        self.client.post(
            self.url,
            data=json.dumps({"hl7_message": ADT_A01}),
            content_type="application/json",
            **self._auth_header(),
        )
        self.assertEqual(HL7MessageLog.objects.count(), before + 1)

    def test_empty_body_returns_400(self):
        """Bug fix: empty hl7_message must return 400, not silently continue."""
        resp = self.client.post(
            self.url,
            data=json.dumps({"hl7_message": ""}),
            content_type="application/json",
            **self._auth_header(),
        )
        self.assertEqual(resp.status_code, 400)

    def test_invalid_hl7_returns_400(self):
        invalid = "PID|1||12345\nNO_MSH_SEGMENT\n"
        resp = self.client.post(
            self.url,
            data=json.dumps({"hl7_message": invalid}),
            content_type="application/json",
            **self._auth_header(),
        )
        self.assertEqual(resp.status_code, 400)

    def test_failed_auth_creates_auth_error_log(self):
        """Auth failures must still produce a FAILED/AUTH log for auditability."""
        before = HL7MessageLog.objects.count()
        self.client.post(
            self.url,
            data=json.dumps({"hl7_message": ADT_A01}),
            content_type="application/json",
        )
        self.assertEqual(HL7MessageLog.objects.count(), before + 1)
        log = HL7MessageLog.objects.order_by("-created_at").first()
        self.assertEqual(log.error_category, HL7MessageLog.ErrorCategory.AUTH)

    def test_source_context_merged_from_json_payload(self):
        resp = self.client.post(
            self.url,
            data=json.dumps({
                "hl7_message": ADT_A01,
                "source_context": {"vendor": "Epic", "system_type": "EMR"},
            }),
            content_type="application/json",
            **self._auth_header(),
        )
        self.assertEqual(resp.status_code, 200)
        log = HL7MessageLog.objects.order_by("-created_at").first()
        self.assertEqual(log.source_context.get("vendor"), "Epic")


# ---------------------------------------------------------------------------
# Patient CSV Import  POST /import/patients/
# ---------------------------------------------------------------------------

CSV_VALID = (
    "mrn,first_name,last_name,dob,gender,address1,city,state,zip_code\n"
    "MRN001,John,Doe,1980-01-15,M,100 Main St,Dallas,TX,75001\n"
    "MRN002,Jane,Smith,1990-06-20,F,200 Oak Ave,Austin,TX,78701\n"
)

CSV_WITH_DUPE = (
    "mrn,first_name,last_name,dob,gender\n"
    "MRN003,Alice,Wong,1985-03-10,F\n"
    "MRN003,Alice,Wong,1985-03-10,F\n"  # duplicate
)

CSV_MISSING_REQUIRED_COL = "mrn,first_name\nMRN004,Bob\n"

CSV_INVALID_DOB = (
    "mrn,first_name,last_name,dob\n"
    "MRN005,Bad,Date,NOT-A-DATE\n"
)

CSV_MISSING_MRN = (
    "mrn,first_name,last_name,dob\n"
    ",No,MRN,1990-01-01\n"
)


class PatientImportTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("patient-import")

    def _upload(self, csv_content, filename="patients.csv"):
        f = io.BytesIO(csv_content.encode())
        f.name = filename
        return self.client.post(self.url, {"csv_file": f}, format="multipart")

    def test_get_returns_200(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

    def test_no_file_shows_error(self):
        resp = self.client.post(self.url, {})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Please choose a CSV file")

    def test_valid_csv_creates_patients(self):
        before = PatientRecord.objects.count()
        self._upload(CSV_VALID)
        self.assertEqual(PatientRecord.objects.count(), before + 2)

    def test_valid_csv_run_completed(self):
        self._upload(CSV_VALID)
        run = PatientImportRun.objects.order_by("-created_at").first()
        self.assertEqual(run.status, PatientImportRun.Status.COMPLETED)
        self.assertEqual(run.inserted, 2)
        self.assertEqual(run.updated, 0)

    def test_duplicate_in_file_counted(self):
        self._upload(CSV_WITH_DUPE)
        run = PatientImportRun.objects.order_by("-created_at").first()
        self.assertEqual(run.duplicates_in_file, 1)
        self.assertEqual(run.inserted, 1)

    def test_missing_required_column_fails(self):
        self._upload(CSV_MISSING_REQUIRED_COL)
        run = PatientImportRun.objects.order_by("-created_at").first()
        self.assertEqual(run.status, PatientImportRun.Status.FAILED)
        self.assertIn("last_name", run.error_message.lower() + run.error_message)

    def test_invalid_dob_is_rejected(self):
        self._upload(CSV_INVALID_DOB)
        run = PatientImportRun.objects.order_by("-created_at").first()
        self.assertEqual(run.rejected, 1)
        self.assertTrue(any("dob" in s.get("reason", "").lower() for s in run.reject_samples))

    def test_missing_mrn_is_rejected(self):
        self._upload(CSV_MISSING_MRN)
        run = PatientImportRun.objects.order_by("-created_at").first()
        self.assertEqual(run.rejected, 1)

    def test_upsert_updates_existing_patient(self):
        PatientRecord.objects.create(mrn="MRN001", first_name="Old", last_name="Name")
        self._upload(CSV_VALID)
        p = PatientRecord.objects.get(mrn="MRN001")
        self.assertEqual(p.first_name, "John")
        run = PatientImportRun.objects.order_by("-created_at").first()
        self.assertEqual(run.updated, 1)
        self.assertEqual(run.inserted, 1)

    def test_rejects_csv_download(self):
        self._upload(CSV_INVALID_DOB)
        run = PatientImportRun.objects.order_by("-created_at").first()
        url = reverse("patient-import-rejects-csv", args=[run.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv; charset=utf-8")
        content = resp.content.decode()
        self.assertIn("rownum", content)
        self.assertIn("reason", content)

    def test_reconciliation_stored(self):
        self._upload(CSV_VALID)
        run = PatientImportRun.objects.order_by("-created_at").first()
        rec = run.reconciliation
        self.assertIn("source_rows", rec)
        self.assertIn("inserted", rec)
        self.assertEqual(rec["inserted"], 2)


# ---------------------------------------------------------------------------
# Home view
# ---------------------------------------------------------------------------

class HomeViewTests(TestCase):
    def test_home_returns_200(self):
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 200)

    def test_home_context_has_total(self):
        resp = self.client.get(reverse("home"))
        self.assertIn("total", resp.context)


# ---------------------------------------------------------------------------
# Mirth messages list / detail
# ---------------------------------------------------------------------------

class MirthMessagesTests(TestCase):
    def setUp(self):
        self.log = HL7MessageLog.objects.create(
            trace_id="test-trace-001",
            source_system="MIRTH",
            message_type="ADT^A01",
            raw_hl7=ADT_A01,
            processing_status=HL7MessageLog.ProcessingStatus.TRANSFORMED,
        )

    def test_messages_list_200(self):
        resp = self.client.get(reverse("mirth-messages"))
        self.assertEqual(resp.status_code, 200)

    def test_messages_filter_by_status(self):
        resp = self.client.get(reverse("mirth-messages") + "?status=TRANSFORMED")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.log, resp.context["logs"])

    def test_messages_filter_by_type(self):
        resp = self.client.get(reverse("mirth-messages") + "?type=ADT")
        self.assertEqual(resp.status_code, 200)

    def test_message_detail_200(self):
        resp = self.client.get(reverse("mirth-message-detail", args=[self.log.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_message_detail_404_for_unknown(self):
        resp = self.client.get(reverse("mirth-message-detail", args=[99999]))
        self.assertEqual(resp.status_code, 404)
