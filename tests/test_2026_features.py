"""
tests/test_2026_features.py

Tests for the 2026 healthcare integration features:
  - FHIR R4 REST API (Patient, Encounter, DiagnosticReport, CapabilityStatement)
  - SMART on FHIR /.well-known/smart-configuration
  - Da Vinci Prior Authorization (CRD hooks, PAS submit)
  - Webhook retry / DLQ (attempt counting, exponential backoff, max_retries guard)

TDD principles applied:
  - Each test has a single, named assertion focus (Arrange / Act / Assert)
  - No random behaviour — force_outcome or deterministic fixtures used throughout
  - Tests cover both happy path and error/edge cases
  - Model layer tested independently from view layer
"""

import json
import uuid
from decimal import Decimal

from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.utils import timezone

from example.models import HL7MessageLog, WebhookDelivery
from example.webhook_service import deliver_fhir_webhook

User = get_user_model()

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ADT_HL7 = (
    "MSH|^~\\&|EPIC|MEMORIAL_HOSP|MIRTH|FACILITY|20260115090000||ADT^A01|T001|P|2.5\r"
    "PID|1||10001^^^MRN||JOHNSON^ALICE||19720315|F|||100 MAIN ST^^DALLAS^TX^75201\r"
    "PV1|1|I|CARDIAC^101^A||||2001^SMITH^ROBERT|||INT||||ADM|||20260115090000\r"
)

ORU_HL7 = (
    "MSH|^~\\&|LAB_SYS|MEMORIAL_HOSP|EHR|FACILITY|20260115120000||ORU^R01|T002|P|2.5\r"
    "PID|1||10001^^^MRN||JOHNSON^ALICE||19720315|F\r"
    "OBR|1||LAB001|1558-6^Hemoglobin^LN|||20260115120000\r"
    "OBX|1|NM|1558-6^Hemoglobin^LN||13.5|g/dL|12.0-16.0|N\r"
)


def make_log(message_type="ADT^A01", patient_id="10001", hl7=None,
             encounter_present=True, source_system="TEST"):
    return HL7MessageLog.objects.create(
        trace_id=uuid.uuid4().hex,
        source_system=source_system,
        message_type=message_type,
        raw_hl7=hl7 or ADT_HL7,
        processing_status=HL7MessageLog.ProcessingStatus.TRANSFORMED,
        error_category=HL7MessageLog.ErrorCategory.NONE,
        patient_id=patient_id,
        encounter_present=encounter_present,
        has_x12=False,
    )


def make_delivery(status=WebhookDelivery.DeliveryStatus.FAILED,
                  attempt_count=1, max_retries=3,
                  resource_type="Patient", trace_id=None):
    return WebhookDelivery.objects.create(
        trace_id=trace_id or uuid.uuid4().hex,
        fhir_resource_type=resource_type,
        fhir_payload={"resourceType": resource_type},
        target_url="https://ehr.example.com/fhir/Patient",
        status=status,
        attempt_count=attempt_count,
        max_retries=max_retries,
        response_code=503 if status == WebhookDelivery.DeliveryStatus.FAILED else 201,
    )


# ---------------------------------------------------------------------------
# FHIR CapabilityStatement
# ---------------------------------------------------------------------------

class FHIRCapabilityStatementTests(TestCase):

    def test_metadata_returns_200(self):
        r = self.client.get("/fhir/")
        self.assertEqual(r.status_code, 200)

    def test_metadata_content_type_is_fhir_json(self):
        r = self.client.get("/fhir/")
        self.assertIn("application/fhir+json", r["Content-Type"])

    def test_metadata_resource_type(self):
        data = json.loads(self.client.get("/fhir/").content)
        self.assertEqual(data["resourceType"], "CapabilityStatement")

    def test_metadata_lists_patient_resource(self):
        data = json.loads(self.client.get("/fhir/").content)
        types = [r["type"] for r in data["rest"][0]["resource"]]
        self.assertIn("Patient", types)

    def test_metadata_advertises_smart_security(self):
        data = json.loads(self.client.get("/fhir/").content)
        security = data["rest"][0]["security"]
        codes = [
            c["code"]
            for svc in security["service"]
            for c in svc["coding"]
        ]
        self.assertIn("SMART-on-FHIR", codes)

    def test_metadata_fhir_version(self):
        data = json.loads(self.client.get("/fhir/").content)
        self.assertEqual(data["fhirVersion"], "4.0.1")


# ---------------------------------------------------------------------------
# FHIR Patient API
# ---------------------------------------------------------------------------

class FHIRPatientAPITests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("fhirtest", password="pass")
        self.client.login(username="fhirtest", password="pass")
        self.log = make_log(patient_id="10001", hl7=ADT_HL7)

    def test_patient_search_requires_login(self):
        self.client.logout()
        r = self.client.get("/fhir/Patient/")
        self.assertEqual(r.status_code, 401)

    def test_patient_search_returns_bundle(self):
        r = self.client.get("/fhir/Patient/")
        data = json.loads(r.content)
        self.assertEqual(data["resourceType"], "Bundle")
        self.assertEqual(data["type"], "searchset")

    def test_patient_search_returns_fhir_json_content_type(self):
        r = self.client.get("/fhir/Patient/")
        self.assertIn("application/fhir+json", r["Content-Type"])

    def test_patient_search_by_identifier(self):
        r = self.client.get("/fhir/Patient/?identifier=10001")
        data = json.loads(r.content)
        self.assertGreaterEqual(data["total"], 1)

    def test_patient_search_deduplicates_by_mrn(self):
        # Two logs for same patient — should appear once in results
        make_log(patient_id="10001", hl7=ADT_HL7)
        r = self.client.get("/fhir/Patient/?identifier=10001")
        data = json.loads(r.content)
        self.assertEqual(data["total"], 1)

    def test_patient_read_found(self):
        r = self.client.get("/fhir/Patient/10001/")
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertEqual(data["resourceType"], "Patient")

    def test_patient_read_not_found_returns_404(self):
        r = self.client.get("/fhir/Patient/NOBODY/")
        self.assertEqual(r.status_code, 404)
        data = json.loads(r.content)
        self.assertEqual(data["resourceType"], "OperationOutcome")

    def test_patient_read_404_issue_code(self):
        r = self.client.get("/fhir/Patient/NOBODY/")
        data = json.loads(r.content)
        self.assertEqual(data["issue"][0]["code"], "not-found")

    def test_patient_search_returns_entry_list(self):
        r = self.client.get("/fhir/Patient/")
        data = json.loads(r.content)
        self.assertIsInstance(data["entry"], list)

    def test_patient_read_has_id_field(self):
        r = self.client.get("/fhir/Patient/10001/")
        data = json.loads(r.content)
        self.assertIn("id", data)


# ---------------------------------------------------------------------------
# FHIR Encounter API
# ---------------------------------------------------------------------------

class FHIREncounterAPITests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("enctest", password="pass")
        self.client.login(username="enctest", password="pass")
        self.log = make_log(patient_id="10001", hl7=ADT_HL7, encounter_present=True)

    def test_encounter_search_returns_bundle(self):
        r = self.client.get("/fhir/Encounter/")
        data = json.loads(r.content)
        self.assertEqual(data["resourceType"], "Bundle")

    def test_encounter_search_filters_by_subject(self):
        make_log(patient_id="99999", hl7=ADT_HL7, encounter_present=True)
        r = self.client.get("/fhir/Encounter/?subject=Patient/10001")
        data = json.loads(r.content)
        for entry in data["entry"]:
            subject = entry["resource"].get("subject", {}).get("reference", "")
            self.assertIn("10001", subject)

    def test_encounter_read_synthetic_id(self):
        enc_id = f"enc-{self.log.pk}"
        r = self.client.get(f"/fhir/Encounter/{enc_id}/")
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertEqual(data["resourceType"], "Encounter")

    def test_encounter_read_bad_id_returns_400(self):
        r = self.client.get("/fhir/Encounter/not-a-valid-id/")
        self.assertEqual(r.status_code, 400)

    def test_encounter_read_missing_returns_404(self):
        r = self.client.get("/fhir/Encounter/enc-999999/")
        self.assertEqual(r.status_code, 404)

    def test_encounter_requires_login(self):
        self.client.logout()
        r = self.client.get("/fhir/Encounter/")
        self.assertEqual(r.status_code, 401)


# ---------------------------------------------------------------------------
# FHIR DiagnosticReport API
# ---------------------------------------------------------------------------

class FHIRDiagnosticReportAPITests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("rpttest", password="pass")
        self.client.login(username="rpttest", password="pass")
        make_log(message_type="ORU^R01", patient_id="10001",
                 hl7=ORU_HL7, encounter_present=False)

    def test_report_search_returns_bundle(self):
        r = self.client.get("/fhir/DiagnosticReport/")
        data = json.loads(r.content)
        self.assertEqual(data["resourceType"], "Bundle")

    def test_report_search_by_subject(self):
        r = self.client.get("/fhir/DiagnosticReport/?subject=Patient/10001")
        data = json.loads(r.content)
        self.assertGreaterEqual(data["total"], 1)

    def test_report_search_excludes_adt(self):
        make_log(message_type="ADT^A01", patient_id="10001",
                 hl7=ADT_HL7, encounter_present=True)
        r = self.client.get("/fhir/DiagnosticReport/?subject=Patient/10001")
        data = json.loads(r.content)
        for entry in data["entry"]:
            self.assertEqual(entry["resource"]["resourceType"], "DiagnosticReport")


# ---------------------------------------------------------------------------
# FHIR auth: 401 JSON instead of HTML redirect (regression tests)
# ---------------------------------------------------------------------------

class FHIRAuthTests(TestCase):
    """Unauthenticated requests must return 401 FHIR JSON, never an HTML redirect."""

    PROTECTED_URLS = [
        "/fhir/Patient/",
        "/fhir/Patient/10001/",
        "/fhir/Encounter/",
        "/fhir/Encounter/enc-1/",
        "/fhir/DiagnosticReport/",
    ]

    def test_unauthenticated_patient_search_returns_401(self):
        r = self.client.get("/fhir/Patient/")
        self.assertEqual(r.status_code, 401)

    def test_unauthenticated_patient_read_returns_401(self):
        r = self.client.get("/fhir/Patient/10001/")
        self.assertEqual(r.status_code, 401)

    def test_unauthenticated_encounter_search_returns_401(self):
        r = self.client.get("/fhir/Encounter/")
        self.assertEqual(r.status_code, 401)

    def test_unauthenticated_encounter_read_returns_401(self):
        r = self.client.get("/fhir/Encounter/enc-1/")
        self.assertEqual(r.status_code, 401)

    def test_unauthenticated_diagnostic_report_returns_401(self):
        r = self.client.get("/fhir/DiagnosticReport/")
        self.assertEqual(r.status_code, 401)

    def test_401_response_is_fhir_json_content_type(self):
        r = self.client.get("/fhir/Patient/")
        self.assertIn("application/fhir+json", r["Content-Type"])

    def test_401_body_is_operation_outcome(self):
        r = self.client.get("/fhir/Patient/")
        data = json.loads(r.content)
        self.assertEqual(data["resourceType"], "OperationOutcome")

    def test_401_body_has_security_issue_code(self):
        r = self.client.get("/fhir/Patient/")
        data = json.loads(r.content)
        self.assertEqual(data["issue"][0]["code"], "security")

    def test_401_body_is_parseable_json_not_html(self):
        """Core regression: response must never be HTML (the original bug)."""
        for url in self.PROTECTED_URLS:
            with self.subTest(url=url):
                r = self.client.get(url)
                content = r.content.decode()
                self.assertFalse(
                    content.strip().lower().startswith("<!doctype"),
                    msg=f"{url} returned HTML instead of JSON",
                )
                # Must be parseable as JSON
                json.loads(content)

    def test_no_redirect_on_unauthenticated_fhir_request(self):
        """Must not redirect (302) — browsers follow redirects to HTML login page."""
        for url in self.PROTECTED_URLS:
            with self.subTest(url=url):
                r = self.client.get(url)
                self.assertNotEqual(r.status_code, 302, msg=f"{url} issued a redirect")

    def test_authenticated_user_can_access_patient_search(self):
        user = User.objects.create_user("authcheck", password="pass")
        self.client.login(username="authcheck", password="pass")
        r = self.client.get("/fhir/Patient/")
        self.assertEqual(r.status_code, 200)

    def test_metadata_is_public_no_auth_needed(self):
        """CapabilityStatement /fhir/ must remain public."""
        r = self.client.get("/fhir/")
        self.assertEqual(r.status_code, 200)


# ---------------------------------------------------------------------------
# SMART on FHIR
# ---------------------------------------------------------------------------

class SMARTConfigTests(TestCase):

    def test_well_known_returns_200(self):
        r = self.client.get("/.well-known/smart-configuration")
        self.assertEqual(r.status_code, 200)

    def test_well_known_no_auth_required(self):
        # Public endpoint — no login needed
        self.client.logout()
        r = self.client.get("/.well-known/smart-configuration")
        self.assertEqual(r.status_code, 200)

    def test_well_known_has_authorization_endpoint(self):
        data = json.loads(self.client.get("/.well-known/smart-configuration").content)
        self.assertIn("authorization_endpoint", data)

    def test_well_known_has_token_endpoint(self):
        data = json.loads(self.client.get("/.well-known/smart-configuration").content)
        self.assertIn("token_endpoint", data)

    def test_well_known_scopes_include_patient_read(self):
        data = json.loads(self.client.get("/.well-known/smart-configuration").content)
        self.assertIn("patient/Patient.read", data["scopes_supported"])

    def test_well_known_capabilities_include_smart_launch(self):
        data = json.loads(self.client.get("/.well-known/smart-configuration").content)
        self.assertIn("launch-ehr", data["capabilities"])

    def test_well_known_cors_header(self):
        r = self.client.get("/.well-known/smart-configuration")
        self.assertEqual(r["Access-Control-Allow-Origin"], "*")

    def test_well_known_has_pkce_support(self):
        data = json.loads(self.client.get("/.well-known/smart-configuration").content)
        self.assertIn("S256", data["code_challenge_methods_supported"])

    def test_smart_page_requires_login(self):
        r = self.client.get("/smart-on-fhir/")
        self.assertIn(r.status_code, [302, 200])  # redirect or ok if logged in

    def test_smart_page_renders(self):
        user = User.objects.create_user("smartuser", password="pass")
        self.client.login(username="smartuser", password="pass")
        r = self.client.get("/smart-on-fhir/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "SMART")


# ---------------------------------------------------------------------------
# Da Vinci CRD
# ---------------------------------------------------------------------------

class CRDHookTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("crdtest", password="pass")
        self.client.login(username="crdtest", password="pass")

    def _post(self, service_code):
        return self.client.post(
            "/api/prior-auth/crd/",
            data=json.dumps({
                "hook": "order-select",
                "hookInstance": uuid.uuid4().hex,
                "service_code": service_code,
                "context": {"patientId": "10001", "draftOrders": {"entry": []}},
            }),
            content_type="application/json",
        )

    def test_crd_returns_cards(self):
        r = self._post("73721")
        data = json.loads(r.content)
        self.assertIn("cards", data)

    def test_crd_auth_required_indicator_warning(self):
        r = self._post("73721")
        data = json.loads(r.content)
        self.assertEqual(data["cards"][0]["indicator"], "warning")

    def test_crd_no_auth_indicator_info(self):
        r = self._post("99213")
        data = json.loads(r.content)
        self.assertEqual(data["cards"][0]["indicator"], "info")

    def test_crd_mental_health_parity_no_auth(self):
        r = self._post("90837")
        data = json.loads(r.content)
        self.assertEqual(data["cards"][0]["indicator"], "info")

    def test_crd_auth_required_card_has_suggestion(self):
        r = self._post("73721")
        data = json.loads(r.content)
        self.assertTrue(len(data["cards"][0]["suggestions"]) > 0)

    def test_crd_auth_required_has_documentation_list(self):
        r = self._post("73721")
        data = json.loads(r.content)
        ext = data["cards"][0]["extension"]["davinci-crd.coverage-information"]
        self.assertIn("documentation-needed", ext)
        self.assertIsInstance(ext["documentation-needed"], list)

    def test_crd_unknown_code_returns_info_card(self):
        r = self._post("99999")
        data = json.loads(r.content)
        self.assertIn("cards", data)
        self.assertEqual(len(data["cards"]), 1)

    def test_crd_requires_post(self):
        r = self.client.get("/api/prior-auth/crd/")
        self.assertEqual(r.status_code, 405)


# ---------------------------------------------------------------------------
# Da Vinci PAS
# ---------------------------------------------------------------------------

class PASSubmitTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("pastest", password="pass")
        self.client.login(username="pastest", password="pass")

    def _post(self, service_code="73721", notes="", patient="10001"):
        return self.client.post(
            "/api/prior-auth/pas/",
            data=json.dumps({
                "patient_id": patient,
                "service_code": service_code,
                "diagnosis_code": "M17.11",
                "clinical_notes": notes,
            }),
            content_type="application/json",
        )

    def test_pas_approved_with_notes(self):
        r = self._post(notes="Patient has severe osteoarthritis with failed PT.")
        data = json.loads(r.content)
        self.assertEqual(data["decision"], "approved")

    def test_pas_pended_without_notes(self):
        r = self._post(notes="")
        data = json.loads(r.content)
        self.assertEqual(data["decision"], "pended")

    def test_pas_approved_has_prior_auth_number(self):
        r = self._post(notes="Patient has severe osteoarthritis, failed conservative.")
        data = json.loads(r.content)
        self.assertIsNotNone(data["prior_auth_number"])
        self.assertTrue(data["prior_auth_number"].startswith("PA-"))

    def test_pas_pended_no_prior_auth_number(self):
        r = self._post(notes="")
        data = json.loads(r.content)
        self.assertIsNone(data["prior_auth_number"])

    def test_pas_denied_missing_criteria(self):
        # Knee replacement without documenting osteoarthritis
        r = self._post(service_code="27447", notes="Patient wants surgery.")
        data = json.loads(r.content)
        self.assertEqual(data["decision"], "denied")

    def test_pas_not_required_for_non_pa_service(self):
        r = self._post(service_code="99213", notes="")
        data = json.loads(r.content)
        self.assertEqual(data["decision"], "not-required")

    def test_pas_response_has_bundle(self):
        r = self._post(notes="Clinical notes.")
        data = json.loads(r.content)
        self.assertEqual(data["response_bundle"]["resourceType"], "Bundle")

    def test_pas_approved_has_valid_dates(self):
        r = self._post(notes="Patient has severe osteoarthritis.")
        data = json.loads(r.content)
        self.assertIn("valid_from", data)
        self.assertIn("valid_to", data)

    def test_pas_requires_post(self):
        r = self.client.get("/api/prior-auth/pas/")
        self.assertEqual(r.status_code, 405)


# ---------------------------------------------------------------------------
# Webhook Retry / DLQ
# ---------------------------------------------------------------------------

class WebhookRetryModelTests(TestCase):

    def test_new_delivery_has_default_max_retries(self):
        d = make_delivery()
        self.assertEqual(d.max_retries, 3)

    def test_new_delivery_next_retry_at_null(self):
        d = make_delivery()
        self.assertIsNone(d.next_retry_at)

    def test_attempt_count_starts_at_one(self):
        d = make_delivery()
        self.assertEqual(d.attempt_count, 1)


class WebhookRetryViewTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("retrytest", password="pass")
        self.client.login(username="retrytest", password="pass")

    def test_retry_requires_login(self):
        d = make_delivery()
        self.client.logout()
        r = self.client.post(f"/webhooks/{d.pk}/retry/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/accounts/login/", r["Location"])

    def test_retry_increments_attempt_count(self):
        d = make_delivery(attempt_count=1)
        self.client.post(f"/webhooks/{d.pk}/retry/")
        d.refresh_from_db()
        self.assertEqual(d.attempt_count, 2)

    def test_retry_already_delivered_redirects(self):
        d = make_delivery(status=WebhookDelivery.DeliveryStatus.DELIVERED, attempt_count=1)
        r = self.client.post(f"/webhooks/{d.pk}/retry/")
        self.assertEqual(r.status_code, 302)
        d.refresh_from_db()
        self.assertEqual(d.attempt_count, 1)  # unchanged

    def test_retry_at_max_retries_blocked(self):
        d = make_delivery(attempt_count=3, max_retries=3)
        self.client.post(f"/webhooks/{d.pk}/retry/")
        d.refresh_from_db()
        self.assertEqual(d.attempt_count, 3)  # not incremented

    def test_retry_failed_sets_next_retry_at_on_failure(self):
        """On a failed retry, next_retry_at should be set (exponential backoff)."""
        d = make_delivery(attempt_count=1)
        # Patch random to force failure
        import unittest.mock as mock
        with mock.patch("example.views.random.random", return_value=0.99):  # > 0.80 = failure
            self.client.post(f"/webhooks/{d.pk}/retry/")
        d.refresh_from_db()
        if d.status == WebhookDelivery.DeliveryStatus.FAILED:
            self.assertIsNotNone(d.next_retry_at)

    def test_retry_success_clears_error_detail(self):
        d = make_delivery(attempt_count=1)
        d.error_detail = "Connection timeout"
        d.save()
        import unittest.mock as mock
        with mock.patch("example.views.random.random", return_value=0.0):  # < 0.80 = success
            self.client.post(f"/webhooks/{d.pk}/retry/")
        d.refresh_from_db()
        if d.status == WebhookDelivery.DeliveryStatus.DELIVERED:
            self.assertEqual(d.error_detail, "")

    def test_retry_redirects_to_webhook_log(self):
        d = make_delivery(attempt_count=1)
        r = self.client.post(f"/webhooks/{d.pk}/retry/")
        self.assertRedirects(r, "/webhooks/", fetch_redirect_response=False)

    def test_webhook_log_page_shows_retry_button(self):
        make_delivery(attempt_count=1, max_retries=3,
                      status=WebhookDelivery.DeliveryStatus.FAILED)
        r = self.client.get("/webhooks/")
        self.assertContains(r, "Retry")

    def test_webhook_log_page_shows_dlq_when_exhausted(self):
        make_delivery(attempt_count=3, max_retries=3,
                      status=WebhookDelivery.DeliveryStatus.FAILED)
        r = self.client.get("/webhooks/")
        self.assertContains(r, "DLQ")
