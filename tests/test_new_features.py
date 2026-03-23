"""
tests/test_new_features.py

TDD tests for the four new features:
  1. SIU scheduling pipeline
  2. ClaimRecord model and reconciliation
  3. User auth (login_required, login/logout flow)
  4. WebhookDelivery model and service

TDD KEY IDEA:
  Each test defines a CONTRACT — a precise statement of what the code
  must do. If the contract changes, the test breaks and forces you to
  make a conscious decision. Tests are documentation that never lies.

TEST ANATOMY:
  Arrange  → set up the data / state
  Act      → call the code under test
  Assert   → verify the outcome

Run with:
  pytest tests/test_new_features.py -v
  python manage.py test tests.test_new_features      (Django runner)
"""
import json
import pytest
from datetime import datetime, timezone

import django
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse

# ──────────────────────────────────────────────────────────────────────────────
# SIU Sample messages
# ──────────────────────────────────────────────────────────────────────────────

# SCH segment field positions (HL7 v2 standard):
#   [1]  SCH-1  Placer Appointment ID
#   [2]  SCH-2  Filler Appointment ID
#   [9]  SCH-9  Appointment Duration (minutes)
#   [11] SCH-11 Appointment Timing Quantity (TQ composite: qty^interval^dur^start^end)
#   [25] SCH-25 Filler Status Code
#
# We pad with empty pipes (|||) to reach the correct field index.
# This is how real HL7 v2 messages work — fields are positional, not named.

SIU_S12 = (
    "MSH|^~\\&|SCHEDULING|HOSPITAL|EHR|FACILITY|20260101090000||SIU^S12|SCH00001|P|2.5\r"
    "SCH|APPT001|FILL001|||||||60||^^^20260115090000||||||||||||||Pending\r"
    "PID|1||PAT001^^^MRN||SMITH^JANE||19750320|F\r"
    "AIS|1||ECHO^Echocardiogram|||30\r"
    "AIP|1||DR001^JONES^ALICE|||30\r"
)

SIU_S15_CANCEL = (
    "MSH|^~\\&|SCHEDULING|HOSPITAL|EHR|FACILITY|20260102100000||SIU^S15|SCH00002|P|2.5\r"
    "SCH|APPT002|FILL002|||||||30||^^^20260116140000||||||||||||||Cancelled\r"
    "PID|1||PAT002^^^MRN||BROWN^BOB||19900610|M\r"
)

SIU_NO_SCH = (
    "MSH|^~\\&|SCHEDULING|HOSPITAL|EHR|FACILITY|20260101090000||SIU^S12|SCH00003|P|2.5\r"
    "PID|1||PAT003^^^MRN||DOE^JOHN||19800101|M\r"
)


# ──────────────────────────────────────────────────────────────────────────────
# Feature 1: SIU scheduling pipeline
# ──────────────────────────────────────────────────────────────────────────────

class SIUParsingTests(TestCase):
    """
    Unit tests for SIU message parsing (no DB needed — these are pure
    function tests against hl7_utils.py).

    WHY TEST THIS:
      SIU is the most common scheduling interface failure point.
      Appointments arrive with missing SCH segments, wrong datetime
      formats, or unmapped status codes. Each test pins one behaviour.
    """

    def test_siu_message_type_detected(self):
        """get_hl7_message_type must extract SIU^S12 from MSH-9."""
        from example.hl7_utils import get_hl7_message_type
        result = get_hl7_message_type(SIU_S12)
        self.assertEqual(result, "SIU^S12")

    def test_siu_routes_to_fhir_appointment(self):
        """hl7_to_all must return an Appointment resource for SIU messages."""
        from example.hl7_utils import hl7_to_all
        result = hl7_to_all(SIU_S12)
        # Contract: result has 'appointment' key with correct resourceType
        self.assertIn("appointment", result)
        self.assertEqual(result["appointment"]["resourceType"], "Appointment")

    def test_siu_appointment_status_booked(self):
        """SCH filler status 'Pending' → FHIR status 'pending'."""
        from example.hl7_utils import hl7_siu_to_fhir
        result = hl7_siu_to_fhir(SIU_S12)
        self.assertEqual(result["appointment"]["status"], "pending")

    def test_siu_appointment_status_cancelled(self):
        """SCH filler status 'Cancelled' → FHIR status 'cancelled'."""
        from example.hl7_utils import hl7_siu_to_fhir
        result = hl7_siu_to_fhir(SIU_S15_CANCEL)
        self.assertEqual(result["appointment"]["status"], "cancelled")

    def test_siu_patient_participant(self):
        """Patient from PID must appear in Appointment.participant."""
        from example.hl7_utils import hl7_siu_to_fhir
        result = hl7_siu_to_fhir(SIU_S12)
        appt = result["appointment"]
        references = [p["actor"]["reference"] for p in appt.get("participant", [])]
        self.assertTrue(any("Patient/PAT001" in r for r in references))

    def test_siu_provider_participant(self):
        """Provider from AIP must appear in Appointment.participant."""
        from example.hl7_utils import hl7_siu_to_fhir
        result = hl7_siu_to_fhir(SIU_S12)
        appt = result["appointment"]
        references = [p["actor"]["reference"] for p in appt.get("participant", [])]
        self.assertTrue(any("Practitioner/DR001" in r for r in references))

    def test_siu_service_type(self):
        """AIS service code must appear in Appointment.serviceType coding."""
        from example.hl7_utils import hl7_siu_to_fhir
        result = hl7_siu_to_fhir(SIU_S12)
        appt = result["appointment"]
        codes = [
            c["code"]
            for st in appt.get("serviceType", [])
            for c in st.get("coding", [])
        ]
        self.assertIn("ECHO", codes)

    def test_siu_patient_id_extracted(self):
        """patient_id at top level of result must match PID-3."""
        from example.hl7_utils import hl7_siu_to_fhir
        result = hl7_siu_to_fhir(SIU_S12)
        self.assertEqual(result["patient_id"], "PAT001^^^MRN")

    def test_siu_validation_requires_sch(self):
        """SIU without SCH segment must produce a validation error."""
        from example.hl7_utils import validate_hl7_message
        errors, warnings = validate_hl7_message(SIU_NO_SCH)
        self.assertTrue(any("SCH" in e for e in errors))

    def test_siu_no_sch_no_crash(self):
        """hl7_siu_to_fhir must not raise even with missing SCH."""
        from example.hl7_utils import hl7_siu_to_fhir
        # Should return a result dict, not raise
        result = hl7_siu_to_fhir(SIU_NO_SCH)
        self.assertIn("appointment", result)

    def test_build_trigger_event_siu(self):
        """build_trigger_event must handle SIU^S12."""
        from example.hl7_utils import build_trigger_event
        te = build_trigger_event("SIU^S12")
        self.assertEqual(te["code"], "S12")
        self.assertIn("Appointment", te["description"])

    def test_build_message_profile_siu(self):
        """build_message_profile must return human-readable SIU label."""
        from example.hl7_utils import build_message_profile
        profile = build_message_profile("SIU^S15")
        self.assertIn("SIU", profile)
        self.assertIn("Cancel", profile)


# ──────────────────────────────────────────────────────────────────────────────
# Feature 2: ClaimRecord model and reconciliation view
# ──────────────────────────────────────────────────────────────────────────────

class ClaimRecordModelTests(TestCase):
    """
    Unit tests for the ClaimRecord model.

    WHY TEST THIS:
      The reconciliation math (billed - paid - patient_resp = balance_due)
      must be exact. Billing errors cost money. Test the model fields
      and __str__ to catch migration or field-type mistakes early.
    """

    def _make_claim(self, **kwargs):
        from example.models import ClaimRecord
        defaults = {
            "claim_id": "CLM001",
            "patient_id": "PAT001",
            "status": ClaimRecord.ClaimStatus.PAID,
            "billed_amount": "150.00",
            "paid_amount": "120.00",
            "patient_responsibility": "30.00",
            "balance_due": "0.00",
        }
        defaults.update(kwargs)
        return ClaimRecord.objects.create(**defaults)

    def test_claim_created_with_correct_amounts(self):
        claim = self._make_claim()
        self.assertEqual(float(claim.billed_amount), 150.00)
        self.assertEqual(float(claim.paid_amount), 120.00)
        self.assertEqual(float(claim.patient_responsibility), 30.00)
        self.assertEqual(float(claim.balance_due), 0.00)

    def test_claim_str_includes_id_and_status(self):
        claim = self._make_claim()
        self.assertIn("CLM001", str(claim))
        self.assertIn("PAID", str(claim))

    def test_claim_default_status_is_submitted(self):
        from example.models import ClaimRecord
        claim = ClaimRecord.objects.create(
            claim_id="CLM002",
            billed_amount="200.00",
        )
        self.assertEqual(claim.status, ClaimRecord.ClaimStatus.SUBMITTED)

    def test_denied_claim_has_zero_paid(self):
        claim = self._make_claim(
            status="DENIED",
            paid_amount="0.00",
            patient_responsibility="0.00",
            balance_due="150.00",
        )
        self.assertEqual(float(claim.paid_amount), 0.00)
        self.assertEqual(float(claim.balance_due), 150.00)


class ClaimReconciliationViewTests(TestCase):
    """
    Integration tests for GET /mirth/claims/reconciliation/.

    WHY TEST THIS:
      The view does a DB aggregate query. If the query breaks (wrong
      field name, missing annotation) it returns a 500. Test that the
      page renders even with zero data, and that status filters work.
    """

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("testbilling", password="pass")
        self.client = Client()
        self.client.login(username="testbilling", password="pass")

    def test_reconciliation_page_renders_empty(self):
        """Page must render 200 even with no claims."""
        url = reverse("claim-reconciliation")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_reconciliation_requires_login(self):
        """Anonymous user must be redirected to login."""
        self.client.logout()
        url = reverse("claim-reconciliation")
        response = self.client.get(url)
        self.assertRedirects(response, f"/accounts/login/?next={url}")

    def test_reconciliation_shows_claims(self):
        from example.models import ClaimRecord
        ClaimRecord.objects.create(
            claim_id="C1", billed_amount="100", paid_amount="80",
            patient_responsibility="20", balance_due="0", status="PAID",
        )
        response = self.client.get(reverse("claim-reconciliation"))
        self.assertContains(response, "C1")

    def test_reconciliation_status_filter(self):
        """Status filter must narrow results."""
        from example.models import ClaimRecord
        ClaimRecord.objects.create(
            claim_id="DENIED01", status="DENIED",
            billed_amount="100", paid_amount="0",
            patient_responsibility="0", balance_due="100",
        )
        ClaimRecord.objects.create(
            claim_id="PAID01", status="PAID",
            billed_amount="100", paid_amount="80",
            patient_responsibility="20", balance_due="0",
        )
        url = reverse("claim-reconciliation") + "?status=DENIED"
        response = self.client.get(url)
        self.assertContains(response, "DENIED01")
        self.assertNotContains(response, "PAID01")


# ──────────────────────────────────────────────────────────────────────────────
# Feature 3: User auth
# ──────────────────────────────────────────────────────────────────────────────

class UserAuthTests(TestCase):
    """
    Integration tests for login/logout and @login_required protection.

    WHY TEST THIS:
      Auth bugs are security bugs. Test that:
        - Protected pages redirect anonymous users
        - Login with correct credentials works
        - Login with wrong credentials fails
        - Logout clears the session

    TDD APPROACH HERE:
      These tests could have been written BEFORE adding @login_required.
      Run them against the original code → they would fail (200 instead
      of 302). Add @login_required → tests pass. That's the TDD loop.
    """

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("analyst", password="securepass")
        self.client = Client()

    # --- Anonymous access ---

    def test_mirth_feed_requires_login(self):
        url = reverse("mirth-messages")
        r = self.client.get(url)
        self.assertRedirects(r, f"/accounts/login/?next={url}")

    def test_patient_import_requires_login(self):
        url = reverse("patient-import")
        r = self.client.get(url)
        self.assertRedirects(r, f"/accounts/login/?next={url}")

    def test_claim_reconciliation_requires_login(self):
        url = reverse("claim-reconciliation")
        r = self.client.get(url)
        self.assertRedirects(r, f"/accounts/login/?next={url}")

    def test_webhook_log_requires_login(self):
        url = reverse("webhook-log")
        r = self.client.get(url)
        self.assertRedirects(r, f"/accounts/login/?next={url}")

    # --- Public pages stay public ---

    def test_home_is_public(self):
        """Home page must be accessible without login."""
        r = self.client.get(reverse("home"))
        self.assertEqual(r.status_code, 200)

    def test_hl7_playground_is_public(self):
        r = self.client.get(reverse("hl7-playground"))
        self.assertEqual(r.status_code, 200)

    def test_health_endpoint_is_public(self):
        r = self.client.get(reverse("health"))
        self.assertEqual(r.status_code, 200)

    # --- Login flow ---

    def test_login_page_renders(self):
        r = self.client.get("/accounts/login/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Sign In")

    def test_login_with_correct_credentials(self):
        r = self.client.post("/accounts/login/", {
            "username": "analyst",
            "password": "securepass",
        }, follow=True)
        self.assertEqual(r.status_code, 200)
        # After login Django redirects to LOGIN_REDIRECT_URL = "/"
        self.assertTrue(r.wsgi_request.user.is_authenticated)

    def test_login_with_wrong_password_fails(self):
        r = self.client.post("/accounts/login/", {
            "username": "analyst",
            "password": "wrongpassword",
        })
        # Re-renders the login form, does not redirect
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.wsgi_request.user.is_authenticated)

    def test_authenticated_user_can_access_mirth_feed(self):
        self.client.login(username="analyst", password="securepass")
        r = self.client.get(reverse("mirth-messages"))
        self.assertEqual(r.status_code, 200)

    def test_logout_clears_session(self):
        self.client.login(username="analyst", password="securepass")
        self.client.post("/accounts/logout/")
        r = self.client.get(reverse("mirth-messages"))
        # Should redirect to login after logout
        self.assertEqual(r.status_code, 302)

    def test_navbar_shows_signin_when_anonymous(self):
        r = self.client.get(reverse("home"))
        self.assertContains(r, "Sign In")

    def test_navbar_shows_username_when_authenticated(self):
        self.client.login(username="analyst", password="securepass")
        r = self.client.get(reverse("home"))
        self.assertContains(r, "analyst")
        self.assertContains(r, "Sign Out")

    # --- create_demo_user management command ---

    def test_create_demo_user_command(self):
        """Management command must create user with expected credentials."""
        from django.core.management import call_command
        call_command("create_demo_user", verbosity=0)
        User = get_user_model()
        user = User.objects.get(username="demo")
        self.assertTrue(user.check_password("demo1234"))
        self.assertFalse(user.is_superuser)

    def test_create_demo_user_idempotent(self):
        """Running command twice must not raise or create duplicates."""
        from django.core.management import call_command
        call_command("create_demo_user", verbosity=0)
        call_command("create_demo_user", verbosity=0)   # second call
        User = get_user_model()
        self.assertEqual(User.objects.filter(username="demo").count(), 1)


# ──────────────────────────────────────────────────────────────────────────────
# Feature 4: Webhook simulation
# ──────────────────────────────────────────────────────────────────────────────

class WebhookDeliveryModelTests(TestCase):
    """
    Unit tests for WebhookDelivery model fields and __str__.
    """

    def _make_delivery(self, **kwargs):
        from example.models import WebhookDelivery
        defaults = {
            "trace_id": "abc123",
            "fhir_resource_type": "Patient",
            "fhir_payload": {"resourceType": "Patient", "id": "P1"},
            "target_url": "https://ehr.example.com/fhir/Patient",
            "status": WebhookDelivery.DeliveryStatus.DELIVERED,
            "response_code": 201,
        }
        defaults.update(kwargs)
        return WebhookDelivery.objects.create(**defaults)

    def test_delivery_created(self):
        d = self._make_delivery()
        self.assertEqual(d.fhir_resource_type, "Patient")
        self.assertEqual(d.response_code, 201)

    def test_delivery_str(self):
        d = self._make_delivery()
        self.assertIn("Patient", str(d))
        self.assertIn("DELIVERED", str(d))

    def test_default_status_is_pending(self):
        from example.models import WebhookDelivery
        d = WebhookDelivery.objects.create(
            trace_id="xyz",
            fhir_payload={"resourceType": "Encounter"},
            fhir_resource_type="Encounter",
        )
        self.assertEqual(d.status, WebhookDelivery.DeliveryStatus.PENDING)


class WebhookServiceTests(TestCase):
    """
    Unit tests for example/webhook_service.py.

    WHY TEST THIS:
      The service has two outcomes (delivered / failed). By forcing the
      outcome we can test each code path without relying on randomness.
      Tests that depend on random.random() are flaky and not trustworthy.

    KEY LEARNING:
      use force_outcome="success" / "failure" to make tests deterministic.
      This is the "seam" pattern — inject control at the boundary.
    """

    def test_forced_success_creates_delivered_record(self):
        from example.webhook_service import deliver_fhir_webhook
        d = deliver_fhir_webhook(
            fhir_payload={"resourceType": "Patient"},
            fhir_resource_type="Patient",
            trace_id="trace001",
            force_outcome="success",
        )
        self.assertEqual(d.status, "DELIVERED")
        self.assertEqual(d.response_code, 201)
        self.assertIsNotNone(d.delivered_at)
        self.assertIsNotNone(d.duration_ms)

    def test_forced_failure_creates_failed_record(self):
        from example.webhook_service import deliver_fhir_webhook
        d = deliver_fhir_webhook(
            fhir_payload={"resourceType": "Patient"},
            fhir_resource_type="Patient",
            trace_id="trace002",
            force_outcome="failure",
        )
        self.assertEqual(d.status, "FAILED")
        self.assertEqual(d.response_code, 503)
        self.assertIsNone(d.delivered_at)
        self.assertNotEqual(d.error_detail, "")

    def test_correct_target_url_for_patient(self):
        from example.webhook_service import deliver_fhir_webhook
        d = deliver_fhir_webhook(
            fhir_payload={"resourceType": "Patient"},
            fhir_resource_type="Patient",
            trace_id="trace003",
            force_outcome="success",
        )
        self.assertIn("Patient", d.target_url)

    def test_correct_target_url_for_appointment(self):
        from example.webhook_service import deliver_fhir_webhook
        d = deliver_fhir_webhook(
            fhir_payload={"resourceType": "Appointment"},
            fhir_resource_type="Appointment",
            trace_id="trace004",
            force_outcome="success",
        )
        self.assertIn("scheduling", d.target_url)

    def test_trace_id_stored_on_delivery(self):
        from example.webhook_service import deliver_fhir_webhook
        d = deliver_fhir_webhook(
            fhir_payload={"resourceType": "Encounter"},
            fhir_resource_type="Encounter",
            trace_id="my-trace-id",
            force_outcome="success",
        )
        self.assertEqual(d.trace_id, "my-trace-id")

    def test_dispatch_webhooks_for_adt_result(self):
        """
        dispatch_webhooks_for_result must create one delivery per FHIR
        resource present in the transform result.

        WHY: ADT produces Patient + Encounter. We want exactly 2 deliveries
        recorded — not 0 (missed) and not 4 (doubled).
        """
        from example.webhook_service import dispatch_webhooks_for_result
        from example.models import WebhookDelivery

        adt_result = {
            "patient": {"resourceType": "Patient", "id": "P1"},
            "encounter": {"resourceType": "Encounter"},
            # no appointment, service_request, etc.
        }
        before = WebhookDelivery.objects.count()
        deliveries = dispatch_webhooks_for_result(adt_result, trace_id="t99")
        after = WebhookDelivery.objects.count()

        self.assertEqual(len(deliveries), 2)
        self.assertEqual(after - before, 2)

    def test_dispatch_webhooks_skips_missing_keys(self):
        """Empty result must produce zero deliveries."""
        from example.webhook_service import dispatch_webhooks_for_result
        from example.models import WebhookDelivery

        before = WebhookDelivery.objects.count()
        deliveries = dispatch_webhooks_for_result({}, trace_id="t100")
        self.assertEqual(len(deliveries), 0)
        self.assertEqual(WebhookDelivery.objects.count(), before)


class WebhookLogViewTests(TestCase):
    """
    Integration tests for GET /webhooks/.
    """

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("ops", password="pass")
        self.client = Client()
        self.client.login(username="ops", password="pass")

    def test_webhook_log_renders_empty(self):
        r = self.client.get(reverse("webhook-log"))
        self.assertEqual(r.status_code, 200)

    def test_webhook_log_requires_login(self):
        self.client.logout()
        url = reverse("webhook-log")
        r = self.client.get(url)
        self.assertRedirects(r, f"/accounts/login/?next={url}")

    def test_webhook_log_shows_deliveries(self):
        from example.models import WebhookDelivery
        WebhookDelivery.objects.create(
            trace_id="t1",
            fhir_resource_type="Patient",
            fhir_payload={"resourceType": "Patient"},
            status="DELIVERED",
            response_code=201,
        )
        r = self.client.get(reverse("webhook-log"))
        self.assertContains(r, "Patient")
        self.assertContains(r, "201")

    def test_webhook_log_status_filter(self):
        from example.models import WebhookDelivery
        WebhookDelivery.objects.create(
            trace_id="t2", fhir_resource_type="Encounter",
            fhir_payload={}, status="FAILED", response_code=503,
        )
        WebhookDelivery.objects.create(
            trace_id="t3", fhir_resource_type="Patient",
            fhir_payload={}, status="DELIVERED", response_code=201,
        )
        r = self.client.get(reverse("webhook-log") + "?status=FAILED")
        self.assertContains(r, "Encounter")
        self.assertNotContains(r, "t3")
