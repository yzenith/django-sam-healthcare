"""
Integration tests for logtrace app — services, API, and UI views.
"""
import json
import pytest
from django.test import TestCase, Client
from django.urls import reverse

from logtrace.models import TraceLog, TraceStep
from logtrace.services import ingest_payload

SAMPLE_HL7 = (
    "MSH|^~\\&|MIRTH|HOSPITAL|REC|FAC|202512181200||ADT^A01|MSG001|P|2.3\n"
    "PID|1||12345^^^MRN||DOE^JOHN||19800101|M\n"
    "PV1|1|I|W^101^1\n"
)

SAMPLE_JSON = json.dumps({"patient_id": "ABC123", "event": "admit"})
SAMPLE_EDI = "ISA*00*          *00*          *ZZ*SENDER*ZZ*RECEIVER*250101*1200*^*00501*000000001*0*T*:~GS*HC*SENDER*RECEIVER~"


# ---------------------------------------------------------------------------
# ingest_payload service
# ---------------------------------------------------------------------------

class IngestPayloadTests(TestCase):

    def test_hl7_creates_trace_log(self):
        log = ingest_payload(raw_payload=SAMPLE_HL7)
        self.assertIsNotNone(log.pk)
        self.assertEqual(log.input_type, "HL7")

    def test_hl7_status_processed(self):
        log = ingest_payload(raw_payload=SAMPLE_HL7)
        self.assertEqual(log.status, TraceLog.Status.PROCESSED)

    def test_hl7_creates_steps(self):
        log = ingest_payload(raw_payload=SAMPLE_HL7)
        self.assertGreater(log.steps.count(), 0)

    def test_hl7_steps_are_ordered(self):
        log = ingest_payload(raw_payload=SAMPLE_HL7)
        seqs = list(log.steps.values_list("sequence", flat=True))
        self.assertEqual(seqs, sorted(seqs))

    def test_hl7_preview_has_message_type(self):
        log = ingest_payload(raw_payload=SAMPLE_HL7)
        self.assertEqual(log.parsed_preview.get("message_type"), "ADT^A01")

    def test_hl7_duration_ms_recorded(self):
        log = ingest_payload(raw_payload=SAMPLE_HL7)
        self.assertIsNotNone(log.duration_ms)
        self.assertGreaterEqual(log.duration_ms, 0)

    def test_hl7_trace_id_unique(self):
        log1 = ingest_payload(raw_payload=SAMPLE_HL7)
        log2 = ingest_payload(raw_payload=SAMPLE_HL7)
        self.assertNotEqual(log1.trace_id, log2.trace_id)

    def test_json_input_type_detected(self):
        log = ingest_payload(raw_payload=SAMPLE_JSON)
        self.assertEqual(log.input_type, "JSON")

    def test_edi_input_type_detected(self):
        log = ingest_payload(raw_payload=SAMPLE_EDI)
        self.assertEqual(log.input_type, "EDI")

    def test_declared_input_type_overrides_detection(self):
        log = ingest_payload(raw_payload=SAMPLE_HL7, declared_input_type="JSON")
        self.assertEqual(log.input_type, "JSON")

    def test_missing_msh_causes_failed_status(self):
        log = ingest_payload(raw_payload="PID|1||12345\nNO_MSH\n", declared_input_type="HL7")
        self.assertEqual(log.status, TraceLog.Status.FAILED)
        self.assertGreater(log.error_count, 0)

    def test_meta_source_system_stored(self):
        log = ingest_payload(raw_payload=SAMPLE_HL7, meta={"source_system": "EpicEMR"})
        self.assertEqual(log.meta.get("source_system"), "EpicEMR")

    def test_meta_source_derived_from_msh_when_absent(self):
        log = ingest_payload(raw_payload=SAMPLE_HL7)
        src = log.meta.get("source_system", "")
        self.assertIn("MIRTH", src)

    def test_meta_message_type_stored(self):
        log = ingest_payload(raw_payload=SAMPLE_HL7)
        self.assertEqual(log.meta.get("message_type"), "ADT^A01")


# ---------------------------------------------------------------------------
# TraceLog model properties
# ---------------------------------------------------------------------------

class TraceLogModelTests(TestCase):

    def _create_log(self, status=TraceLog.Status.PROCESSED, error_count=0):
        return TraceLog.objects.create(
            trace_id=f"test-{TraceLog.objects.count()}",
            input_type="HL7",
            status=status,
            error_count=error_count,
            raw_payload=SAMPLE_HL7,
            parsed_preview={"type": "HL7", "message_type": "ADT^A01"},
            meta={"source_system": "MIRTH"},
        )

    def test_message_type_from_preview(self):
        log = self._create_log()
        self.assertEqual(log.message_type, "ADT^A01")

    def test_source_system_from_meta(self):
        log = self._create_log()
        self.assertEqual(log.source_system, "MIRTH")

    def test_trace_available_false_when_no_steps(self):
        log = self._create_log()
        self.assertFalse(log.trace_available)

    def test_trace_available_true_when_steps_exist(self):
        log = self._create_log()
        TraceStep.objects.create(trace_log=log, sequence=1, step_name="parse", status="OK")
        self.assertTrue(log.trace_available)

    def test_review_required_for_failed(self):
        log = self._create_log(status=TraceLog.Status.FAILED)
        self.assertTrue(log.review_required)

    def test_review_required_for_error_count(self):
        log = self._create_log(error_count=2)
        self.assertTrue(log.review_required)

    def test_review_not_required_for_clean_log(self):
        log = self._create_log()
        TraceStep.objects.create(trace_log=log, sequence=1, step_name="parse", status="OK")
        self.assertFalse(log.review_required)

    def test_processing_status_success(self):
        log = self._create_log()
        TraceStep.objects.create(trace_log=log, sequence=1, step_name="parse", status="OK")
        self.assertEqual(log.processing_status, "SUCCESS")

    def test_processing_status_failed_transformation(self):
        log = self._create_log(status=TraceLog.Status.FAILED)
        self.assertEqual(log.processing_status, "FAILED_TRANSFORMATION")

    def test_processing_status_success_with_warnings(self):
        log = self._create_log()
        TraceStep.objects.create(trace_log=log, sequence=1, step_name="validate", status="WARN", message="Minor warning")
        self.assertEqual(log.processing_status, "SUCCESS_WITH_WARNINGS")

    def test_business_impact_high_for_failed_adt(self):
        log = self._create_log(status=TraceLog.Status.FAILED)
        self.assertEqual(log.business_impact, "High")

    def test_business_impact_low_for_clean(self):
        log = self._create_log()
        TraceStep.objects.create(trace_log=log, sequence=1, step_name="parse", status="OK")
        self.assertEqual(log.business_impact, "Low")

    def test_business_impact_override_via_meta(self):
        log = TraceLog.objects.create(
            trace_id="meta-override-test",
            input_type="HL7",
            status=TraceLog.Status.PROCESSED,
            raw_payload=SAMPLE_HL7,
            meta={"business_impact": "High"},
        )
        self.assertEqual(log.business_impact, "High")


# ---------------------------------------------------------------------------
# Ingest API  POST /api/trace/ingest/
# ---------------------------------------------------------------------------

class IngestAPITests(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("trace-ingest")

    def test_valid_hl7_returns_201(self):
        resp = self.client.post(
            self.url,
            data=json.dumps({"raw_payload": SAMPLE_HL7, "input_type": "HL7"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertIn("trace_id", resp.json())

    def test_valid_json_returns_201(self):
        resp = self.client.post(
            self.url,
            data=json.dumps({"raw_payload": SAMPLE_JSON, "input_type": "JSON"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)

    def test_missing_raw_payload_returns_400(self):
        resp = self.client.post(
            self.url,
            data=json.dumps({"input_type": "HL7"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_creates_trace_log_in_db(self):
        before = TraceLog.objects.count()
        self.client.post(
            self.url,
            data=json.dumps({"raw_payload": SAMPLE_HL7}),
            content_type="application/json",
        )
        self.assertEqual(TraceLog.objects.count(), before + 1)


# ---------------------------------------------------------------------------
# TraceLog List API  GET /api/trace/logs/
# ---------------------------------------------------------------------------

class TraceLogListAPITests(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("trace-logs")
        ingest_payload(raw_payload=SAMPLE_HL7)
        ingest_payload(raw_payload=SAMPLE_JSON)

    def test_returns_200(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

    def test_returns_both_logs(self):
        resp = self.client.get(self.url)
        self.assertGreaterEqual(len(resp.json()), 2)

    def test_filter_by_input_type_hl7(self):
        resp = self.client.get(self.url + "?input_type=HL7")
        data = resp.json()
        self.assertTrue(all(r["input_type"] == "HL7" for r in data))

    def test_filter_by_status(self):
        resp = self.client.get(self.url + "?status=PROCESSED")
        data = resp.json()
        self.assertTrue(all(r["status"] == "PROCESSED" for r in data))

    def test_filter_has_errors(self):
        ingest_payload(raw_payload="BAD_PAYLOAD", declared_input_type="HL7")
        resp = self.client.get(self.url + "?has_errors=true")
        data = resp.json()
        self.assertTrue(all(r["error_count"] > 0 for r in data))


# ---------------------------------------------------------------------------
# TraceLog Detail API  GET /api/trace/logs/<trace_id>/
# ---------------------------------------------------------------------------

class TraceLogDetailAPITests(TestCase):
    def setUp(self):
        self.client = Client()
        self.log = ingest_payload(raw_payload=SAMPLE_HL7)
        self.url = reverse("trace-log-detail", args=[self.log.trace_id])

    def test_returns_200(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

    def test_contains_steps(self):
        resp = self.client.get(self.url)
        body = resp.json()
        self.assertIn("steps", body)
        self.assertGreater(len(body["steps"]), 0)

    def test_unknown_trace_id_returns_404(self):
        resp = self.client.get(reverse("trace-log-detail", args=["nonexistent-trace-xyz"]))
        self.assertEqual(resp.status_code, 404)


# ---------------------------------------------------------------------------
# Trace UI pages
# ---------------------------------------------------------------------------

class TraceUITests(TestCase):
    def setUp(self):
        self.client = Client()
        self.log = ingest_payload(raw_payload=SAMPLE_HL7)

    def test_log_list_page_200(self):
        resp = self.client.get(reverse("trace-logs-page"))
        self.assertEqual(resp.status_code, 200)

    def test_log_detail_page_200(self):
        resp = self.client.get(reverse("trace-detail-page", args=[self.log.trace_id]))
        self.assertEqual(resp.status_code, 200)

    def test_log_detail_page_404_unknown(self):
        resp = self.client.get(reverse("trace-detail-page", args=["no-such-trace"]))
        self.assertEqual(resp.status_code, 404)

    def test_ingest_page_get_200(self):
        resp = self.client.get(reverse("trace-ingest-page"))
        self.assertEqual(resp.status_code, 200)
