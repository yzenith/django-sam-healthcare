"""
sftpingest/tests.py
~~~~~~~~~~~~~~~~~~~
Unit tests for the flat-file parser.

Run with:  python manage.py test sftpingest
"""

from datetime import date
from django.test import TestCase
from .parser import (
    parse_flat_file,
    _detect_delimiter,
    _detect_schema,
    _validate_patient_row,
    _validate_clinical_row,
    _parse_date,
)


# ── Delimiter detection ────────────────────────────────────────────────────────

class TestDetectDelimiter(TestCase):

    def test_comma_csv(self):
        char, name = _detect_delimiter("mrn,first_name,last_name,dob")
        self.assertEqual(char, ",")
        self.assertEqual(name, "COMMA")

    def test_pipe(self):
        char, name = _detect_delimiter("mrn|first_name|last_name|dob")
        self.assertEqual(char, "|")
        self.assertEqual(name, "PIPE")

    def test_tab(self):
        char, name = _detect_delimiter("mrn\tfirst_name\tlast_name\tdob")
        self.assertEqual(char, "\t")
        self.assertEqual(name, "TAB")

    def test_fallback_to_comma_on_empty(self):
        char, name = _detect_delimiter("singlecolumnheader")
        self.assertEqual(char, ",")


# ── Schema detection ───────────────────────────────────────────────────────────

class TestDetectSchema(TestCase):

    def test_patient_schema(self):
        self.assertEqual(_detect_schema(["mrn", "first_name", "last_name", "dob"]), "PATIENT")

    def test_clinical_schema(self):
        self.assertEqual(_detect_schema(["mrn", "visit_date", "diagnosis_code"]), "CLINICAL")

    def test_clinical_takes_priority_over_patient(self):
        # A file with both mrn (patient signal) and visit_date (clinical signal)
        # should be treated as CLINICAL because clinical signals are checked first
        self.assertEqual(_detect_schema(["mrn", "visit_date", "first_name"]), "CLINICAL")

    def test_unknown_schema(self):
        self.assertEqual(_detect_schema(["employee_id", "department", "salary"]), "UNKNOWN")

    def test_case_insensitive(self):
        self.assertEqual(_detect_schema(["MRN", "FIRST_NAME", "LAST_NAME", "DOB"]), "PATIENT")


# ── Date parsing ───────────────────────────────────────────────────────────────

class TestParseDate(TestCase):

    def test_iso_format(self):
        self.assertEqual(_parse_date("1990-05-15"), date(1990, 5, 15))

    def test_compact_format(self):
        self.assertEqual(_parse_date("19900515"), date(1990, 5, 15))

    def test_us_slash_format(self):
        self.assertEqual(_parse_date("05/15/1990"), date(1990, 5, 15))

    def test_invalid_returns_none(self):
        self.assertIsNone(_parse_date("not-a-date"))
        self.assertIsNone(_parse_date(""))
        self.assertIsNone(_parse_date("99/99/9999"))

    def test_strips_whitespace(self):
        self.assertEqual(_parse_date("  1990-05-15  "), date(1990, 5, 15))


# ── Patient row validation ─────────────────────────────────────────────────────

class TestValidatePatientRow(TestCase):

    def _valid_row(self, **overrides):
        base = {
            "mrn": "P-001",
            "first_name": "John",
            "last_name": "Smith",
            "dob": "1990-01-15",
            "gender": "M",
            "state": "MA",
        }
        base.update(overrides)
        return base

    def test_valid_row_returns_record(self):
        record, errors = _validate_patient_row(2, self._valid_row())
        self.assertIsNotNone(record)
        self.assertEqual(errors, [])
        self.assertEqual(record["mrn"], "P-001")
        self.assertEqual(record["first_name"], "John")
        self.assertIsInstance(record["dob"], date)

    def test_missing_mrn(self):
        _, errors = _validate_patient_row(2, self._valid_row(mrn=""))
        self.assertTrue(any(e["field"] == "mrn" for e in errors))

    def test_missing_last_name(self):
        _, errors = _validate_patient_row(2, self._valid_row(last_name=""))
        self.assertTrue(any(e["field"] == "last_name" for e in errors))

    def test_missing_dob(self):
        _, errors = _validate_patient_row(2, self._valid_row(dob=""))
        self.assertTrue(any(e["field"] == "dob" for e in errors))

    def test_invalid_dob_format(self):
        _, errors = _validate_patient_row(2, self._valid_row(dob="15-Jan-1990"))
        self.assertTrue(any(e["field"] == "dob" for e in errors))

    def test_future_dob(self):
        _, errors = _validate_patient_row(2, self._valid_row(dob="2099-01-01"))
        self.assertTrue(any("future" in e["error"].lower() for e in errors))

    def test_gender_mapping(self):
        for raw, expected in [("M","M"),("male","M"),("f","F"),("Female","F"),("u","U"),("o","O")]:
            record, _ = _validate_patient_row(2, self._valid_row(gender=raw))
            self.assertEqual(record["gender"], expected, f"Failed for gender={raw!r}")

    def test_invalid_gender_is_error(self):
        _, errors = _validate_patient_row(2, self._valid_row(gender="X"))
        self.assertTrue(any(e["field"] == "gender" for e in errors))

    def test_empty_gender_is_ok(self):
        record, errors = _validate_patient_row(2, self._valid_row(gender=""))
        self.assertIsNotNone(record)
        self.assertEqual(errors, [])

    def test_state_normalised_to_uppercase(self):
        record, _ = _validate_patient_row(2, self._valid_row(state="ma"))
        self.assertEqual(record["state"], "MA")

    def test_missing_required_fields_returns_none_record(self):
        record, errors = _validate_patient_row(2, self._valid_row(mrn=""))
        self.assertIsNone(record)
        self.assertTrue(len(errors) > 0)


# ── Clinical row validation ────────────────────────────────────────────────────

class TestValidateClinicalRow(TestCase):

    def _valid_row(self, **overrides):
        base = {
            "mrn":            "P-001",
            "visit_date":     "2024-03-15",
            "visit_type":     "EMERGENCY",
            "diagnosis_code": "Z87.891",
            "procedure_code": "99284",
            "provider_id":    "PROV-101",
            "facility_code":  "FAC-1",
            "notes":          "",
        }
        base.update(overrides)
        return base

    def test_valid_row(self):
        record, errors = _validate_clinical_row(2, self._valid_row())
        self.assertIsNotNone(record)
        self.assertEqual(errors, [])
        self.assertIsInstance(record["visit_date"], date)

    def test_missing_mrn(self):
        _, errors = _validate_clinical_row(2, self._valid_row(mrn=""))
        self.assertTrue(any(e["field"] == "mrn" for e in errors))

    def test_missing_visit_date(self):
        _, errors = _validate_clinical_row(2, self._valid_row(visit_date=""))
        self.assertTrue(any(e["field"] == "visit_date" for e in errors))

    def test_future_visit_date(self):
        _, errors = _validate_clinical_row(2, self._valid_row(visit_date="2099-12-31"))
        self.assertTrue(any("future" in e["error"].lower() for e in errors))

    def test_valid_icd10_codes(self):
        for code in ["Z87.891", "A00", "B99.9", "Z00.00", "M54.5"]:
            record, errors = _validate_clinical_row(2, self._valid_row(diagnosis_code=code))
            self.assertIsNotNone(record, f"Should accept ICD-10 code {code!r}")

    def test_invalid_icd10_code(self):
        _, errors = _validate_clinical_row(2, self._valid_row(diagnosis_code="NOTVALID!!"))
        self.assertTrue(any(e["field"] == "diagnosis_code" for e in errors))

    def test_empty_diagnosis_code_ok(self):
        record, errors = _validate_clinical_row(2, self._valid_row(diagnosis_code=""))
        self.assertIsNotNone(record)
        self.assertEqual(errors, [])

    def test_valid_cpt_codes(self):
        for code in ["99284", "99213", "93000", "36415"]:
            record, errors = _validate_clinical_row(2, self._valid_row(procedure_code=code))
            self.assertIsNotNone(record, f"Should accept CPT code {code!r}")

    def test_valid_hcpcs_code(self):
        record, errors = _validate_clinical_row(2, self._valid_row(procedure_code="G0439"))
        self.assertIsNotNone(record)

    def test_invalid_procedure_code(self):
        _, errors = _validate_clinical_row(2, self._valid_row(procedure_code="XXXX!!!"))
        self.assertTrue(any(e["field"] == "procedure_code" for e in errors))


# ── Full parse_flat_file integration ───────────────────────────────────────────

PATIENT_CSV = b"""mrn,first_name,last_name,dob,gender,state
P-001,John,Smith,1990-01-15,M,MA
P-002,Jane,Doe,1985-06-20,F,NY
P-003,,Jones,1970-03-10,M,TX
"""

PATIENT_PIPE = b"""mrn|first_name|last_name|dob|gender
P-001|John|Smith|1990-01-15|M
P-002|Jane|Doe|1985-06-20|F
"""

CLINICAL_CSV = b"""mrn,visit_date,visit_type,diagnosis_code,procedure_code,provider_id
P-001,2024-03-15,EMERGENCY,Z87.891,99284,PROV-101
P-002,2024-03-16,OUTPATIENT,E11.9,99213,PROV-102
P-003,2024-03-17,INPATIENT,BADCODE!!,99999!!,PROV-103
"""

UNKNOWN_HEADERS = b"""employee_id,department,hire_date\n001,Engineering,2020-01-01\n"""

EMPTY_FILE = b""


class TestParseFlatFile(TestCase):

    def test_patient_csv_happy_path(self):
        result = parse_flat_file(PATIENT_CSV, "patients.csv")
        self.assertEqual(result.schema_type, "PATIENT")
        self.assertEqual(result.delimiter_name, "COMMA")
        self.assertEqual(result.total_rows, 3)
        self.assertEqual(result.valid_rows, 2)   # P-003 missing first_name
        self.assertEqual(result.rejected_rows, 1)
        self.assertEqual(result.fatal_error, "")

    def test_pipe_delimiter_detected(self):
        result = parse_flat_file(PATIENT_PIPE, "patients.txt")
        self.assertEqual(result.delimiter_name, "PIPE")
        self.assertEqual(result.valid_rows, 2)

    def test_clinical_csv(self):
        result = parse_flat_file(CLINICAL_CSV, "clinical.csv")
        self.assertEqual(result.schema_type, "CLINICAL")
        self.assertEqual(result.valid_rows, 2)
        self.assertEqual(result.rejected_rows, 1)  # P-003 has bad dx/proc codes

    def test_unknown_schema_is_fatal(self):
        result = parse_flat_file(UNKNOWN_HEADERS, "hr.csv")
        self.assertEqual(result.schema_type, "UNKNOWN")
        self.assertNotEqual(result.fatal_error, "")

    def test_empty_file_is_fatal(self):
        result = parse_flat_file(EMPTY_FILE, "empty.csv")
        self.assertNotEqual(result.fatal_error, "")

    def test_intrafile_duplicate_mrns(self):
        csv = b"mrn,first_name,last_name,dob\nP-001,John,Smith,1990-01-15\nP-001,John,Smith,1990-01-15\n"
        result = parse_flat_file(csv, "dups.csv")
        self.assertEqual(result.valid_rows, 1)
        self.assertEqual(result.duplicate_mrns, 1)

    def test_validation_errors_logged_per_field(self):
        result = parse_flat_file(PATIENT_CSV, "patients.csv")
        error_fields = [e["field"] for e in result.validation_errors]
        self.assertIn("first_name", error_fields)

    def test_utf8_bom_handled(self):
        bom_csv = b"\xef\xbb\xbfmrn,first_name,last_name,dob\nP-001,John,Smith,1990-01-15\n"
        result = parse_flat_file(bom_csv, "bom.csv")
        self.assertEqual(result.valid_rows, 1)

    def test_valid_records_have_date_objects(self):
        result = parse_flat_file(PATIENT_CSV, "patients.csv")
        for rec in result.valid_records:
            self.assertIsInstance(rec["dob"], date)
