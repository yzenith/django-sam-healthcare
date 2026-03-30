"""
ccda/tests.py
~~~~~~~~~~~~~
Unit tests for the C-CDA R2.1 XML generator.

Run with:  python manage.py test ccda
"""

from datetime import date
from django.test import TestCase
from .generator import generate_ccda, _e, _ts


PATIENT = {
    "mrn":        "P-00042",
    "first_name": "John",
    "last_name":  "Smith",
    "dob":        date(1980, 3, 15),
    "gender":     "M",
    "address1":   "123 Main St",
    "city":       "Boston",
    "state":      "MA",
    "zip_code":   "02101",
}

CLINICAL_RECORDS = [
    {
        "mrn":            "P-00042",
        "visit_date":     date(2024, 3, 15),
        "visit_type":     "EMERGENCY",
        "diagnosis_code": "Z87.891",
        "procedure_code": "99284",
        "provider_id":    "PROV-101",
        "facility_code":  "FAC-1",
        "notes":          "Follow-up required.",
    },
    {
        "mrn":            "P-00042",
        "visit_date":     date(2024, 6, 1),
        "visit_type":     "OUTPATIENT",
        "diagnosis_code": "E11.9",
        "procedure_code": "99213",
        "provider_id":    "PROV-102",
        "facility_code":  "FAC-1",
        "notes":          "",
    },
]


class TestGenerateCCDA(TestCase):

    def setUp(self):
        self.xml = generate_ccda(PATIENT, CLINICAL_RECORDS, "CCD")

    # ── Document structure ────────────────────────────────────────────────

    def test_returns_string(self):
        self.assertIsInstance(self.xml, str)

    def test_is_valid_xml_declaration(self):
        self.assertTrue(self.xml.startswith('<?xml version="1.0" encoding="UTF-8"?>'))

    def test_contains_clinical_document_root(self):
        self.assertIn("<ClinicalDocument", self.xml)
        self.assertIn("</ClinicalDocument>", self.xml)

    def test_contains_cda_r2_template(self):
        self.assertIn("2.16.840.1.113883.10.20.22.1.1", self.xml)

    def test_contains_ccd_r21_template(self):
        self.assertIn("2.16.840.1.113883.10.20.22.1.2.1", self.xml)

    def test_loinc_ccd_code(self):
        self.assertIn('code="34133-9"', self.xml)

    # ── Patient demographics ───────────────────────────────────────────────

    def test_patient_mrn_present(self):
        self.assertIn('extension="P-00042"', self.xml)

    def test_patient_name_present(self):
        self.assertIn("<given>John</given>", self.xml)
        self.assertIn("<family>Smith</family>", self.xml)

    def test_patient_gender_code(self):
        self.assertIn('code="M"', self.xml)

    def test_patient_dob(self):
        self.assertIn("19800315", self.xml)

    def test_patient_address(self):
        self.assertIn("Boston", self.xml)
        self.assertIn("MA", self.xml)

    # ── Sections ──────────────────────────────────────────────────────────

    def test_allergies_section_present(self):
        self.assertIn('code="48765-2"', self.xml)
        self.assertIn("No known allergies", self.xml)

    def test_problem_list_section_present(self):
        self.assertIn('code="11450-4"', self.xml)

    def test_encounters_section_present(self):
        self.assertIn('code="46240-8"', self.xml)

    def test_diagnosis_codes_in_xml(self):
        self.assertIn("Z87.891", self.xml)
        self.assertIn("E11.9", self.xml)

    def test_procedure_codes_in_xml(self):
        self.assertIn("99284", self.xml)

    # ── Document types ─────────────────────────────────────────────────────

    def test_discharge_summary_code(self):
        xml = generate_ccda(PATIENT, [], "DISCHARGE_SUMMARY")
        self.assertIn('code="18842-5"', xml)
        self.assertIn("Discharge Summary", xml)

    def test_progress_note_code(self):
        xml = generate_ccda(PATIENT, [], "PROGRESS_NOTE")
        self.assertIn('code="11506-3"', xml)

    # ── Edge cases ─────────────────────────────────────────────────────────

    def test_no_clinical_records(self):
        xml = generate_ccda(PATIENT, [], "CCD")
        self.assertIn("No encounters on record", xml)
        self.assertIn("No known problems on record", xml)

    def test_xml_escaping(self):
        patient_xss = {**PATIENT, "first_name": "<script>alert(1)</script>"}
        xml = generate_ccda(patient_xss, [], "CCD")
        self.assertNotIn("<script>", xml)
        self.assertIn("&lt;script&gt;", xml)

    def test_unique_document_ids(self):
        xml1 = generate_ccda(PATIENT, [], "CCD")
        xml2 = generate_ccda(PATIENT, [], "CCD")
        # Extract the root id from each — they must differ
        import re
        ids = re.findall(r'<id root="([a-f0-9-]{36})"', xml1)
        ids2 = re.findall(r'<id root="([a-f0-9-]{36})"', xml2)
        self.assertNotEqual(ids[0], ids2[0])


class TestHelpers(TestCase):

    def test_e_escapes_html(self):
        self.assertEqual(_e("<b>hello</b>"), "&lt;b&gt;hello&lt;/b&gt;")
        self.assertEqual(_e('say "hi"'), "say &quot;hi&quot;")

    def test_ts_date(self):
        self.assertEqual(_ts(date(1980, 3, 15)), "19800315")

    def test_ts_none_returns_current_timestamp(self):
        result = _ts(None)
        self.assertEqual(len(result), 14)  # YYYYMMDDHHmmss
        self.assertTrue(result.isdigit())
