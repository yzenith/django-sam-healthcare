"""
scheduling/tests.py
~~~~~~~~~~~~~~~~~~~
Unit and integration tests for the SIU scheduling module.

Run with:  python manage.py test scheduling
"""

from datetime import datetime, timedelta
from django.test import TestCase, Client
from django.urls import reverse
import json

from .hl7_generator import generate_siu
from .models import SIUMessage


APPT_DT = datetime(2026, 6, 15, 14, 0, 0)


# ── HL7 generator ─────────────────────────────────────────────────────────────

class TestGenerateSIU(TestCase):

    def _gen(self, event_type="S12", **kwargs):
        defaults = dict(
            patient_id       = "P-00042",
            event_type       = event_type,
            appointment_id   = "APPT-TEST-001",
            appointment_dt   = APPT_DT,
            duration_minutes = 30,
            appointment_type = "ROUTINE",
            provider_id      = "PROV-101",
            provider_name    = "Dr. Test",
            location         = "CLINIC-1",
            reason           = "Annual physical",
        )
        defaults.update(kwargs)
        return generate_siu(**defaults)

    def test_returns_string(self):
        self.assertIsInstance(self._gen(), str)

    def test_cr_segment_separator(self):
        hl7 = self._gen()
        self.assertIn("\r", hl7)

    def test_msh_segment_present(self):
        hl7 = self._gen()
        self.assertTrue(hl7.startswith("MSH|"))

    def test_event_type_in_msh(self):
        for ev in ("S12", "S14", "S15"):
            hl7 = self._gen(event_type=ev)
            self.assertIn(f"SIU^{ev}", hl7)

    def test_sch_segment_present(self):
        hl7 = self._gen()
        segments = hl7.split("\r")
        names = [s[:3] for s in segments if s]
        self.assertIn("SCH", names)

    def test_all_required_segments(self):
        hl7 = self._gen()
        segments = set(s[:3] for s in hl7.split("\r") if s)
        for seg in ("MSH", "SCH", "PID", "PV1", "RGS", "AIS", "AIL", "AIP"):
            self.assertIn(seg, segments, f"Segment {seg} missing")

    def test_patient_id_in_pid(self):
        hl7 = self._gen(patient_id="P-00099")
        self.assertIn("P-00099", hl7)

    def test_appointment_id_in_sch(self):
        hl7 = self._gen(appointment_id="APPT-XYZ")
        self.assertIn("APPT-XYZ", hl7)

    def test_s12_placer_status_booked(self):
        hl7 = self._gen(event_type="S12")
        self.assertIn("Booked", hl7)

    def test_s14_placer_status_modified(self):
        hl7 = self._gen(event_type="S14")
        self.assertIn("Modified", hl7)

    def test_s15_placer_status_cancelled(self):
        hl7 = self._gen(event_type="S15")
        self.assertIn("Cancelled", hl7)

    def test_duration_in_ais(self):
        hl7 = self._gen(duration_minutes=60)
        self.assertIn("60", hl7)

    def test_location_in_ail(self):
        hl7 = self._gen(location="RADIOLOGY")
        self.assertIn("RADIOLOGY", hl7)


# ── REST API ───────────────────────────────────────────────────────────────────

class TestSIUTriggerAPI(TestCase):

    def setUp(self):
        self.client = Client(enforce_csrf_checks=False)
        self.url = reverse("siu-trigger")

    def _payload(self, **overrides):
        base = {
            "patient_id":       "P-00042",
            "event_type":       "S12",
            "appointment_dt":   "2026-06-15T14:00:00",
            "duration_minutes": 30,
            "appointment_type": "ROUTINE",
        }
        base.update(overrides)
        return base

    def test_create_s12(self):
        resp = self.client.post(
            self.url,
            data=json.dumps(self._payload()),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["event_type"], "S12")
        self.assertEqual(data["patient_id"], "P-00042")
        self.assertIn("raw_hl7", data)

    def test_raw_hl7_contains_msh(self):
        resp = self.client.post(
            self.url,
            data=json.dumps(self._payload()),
            content_type="application/json",
        )
        self.assertIn("MSH|", resp.json()["raw_hl7"])

    def test_s15_cancellation(self):
        resp = self.client.post(
            self.url,
            data=json.dumps(self._payload(event_type="S15")),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["event_type"], "S15")

    def test_missing_patient_id_returns_400(self):
        payload = self._payload()
        del payload["patient_id"]
        resp = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_invalid_event_type_returns_400(self):
        resp = self.client.post(
            self.url,
            data=json.dumps(self._payload(event_type="S99")),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_message_stored_in_db(self):
        before = SIUMessage.objects.count()
        self.client.post(
            self.url,
            data=json.dumps(self._payload()),
            content_type="application/json",
        )
        self.assertEqual(SIUMessage.objects.count(), before + 1)

    def test_list_endpoint(self):
        resp = self.client.get(reverse("siu-message-list"))
        self.assertEqual(resp.status_code, 200)
