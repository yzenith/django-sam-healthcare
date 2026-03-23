"""
Unit tests for example/hl7_utils.py.
All tests are pure-Python (no DB required).
"""
import pytest
from example.hl7_utils import (
    normalize_hl7,
    get_hl7_message_type,
    redact_hl7_basic,
    hl7_to_all,
    hl7_to_fhir_patient,
    hl7_to_fhir_encounter,
    extract_hl7_summary,
    validate_hl7_message,
    parse_hl7,
    build_message_profile,
    build_trigger_event,
    fhir_to_837_claim,
    generate_835_from_837,
    reconcile_837_835,
    hl7_oru_to_fhir,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

ADT_A01 = (
    "MSH|^~\\&|MIRTH|SENDING|RECV|FAC|202512181200||ADT^A01|MSG00001|P|2.3\r"
    "PID|1||12345^^^MRN||DOE^JOHN||19800101|M|||123 MAIN ST^^ALLEN^TX^75013||555-5555\r"
    "PV1|1|I|W^101^1\r"
)

ADT_A01_SHORT_TS = (
    "MSH|^~\\&|MIRTH|SENDING|RECV|FAC|202512181200||ADT^A01|MSG00001|P|2.3\n"
    "PID|1||12345^^^MRN||DOE^JOHN||19800101|M\n"
    "PV1|1|O|CLINIC^101\n"
)

ORU_R01 = (
    "MSH|^~\\&|LAB|HOSP|REC|FAC|20251218120000||ORU^R01|MSG00002|P|2.3\n"
    "PID|||67890^^^MRN||SMITH^JANE||19900215|F\n"
    "OBR|1||LAB001|58410-2^CBC WITH DIFFERENTIAL\n"
    "OBX|1|NM|718-7^Hemoglobin||13.5|g/dL|12.0-16.0|N\n"
    "OBX|2|NM|4544-3^Hematocrit||40.2|%|37.0-47.0|N\n"
)


# ---------------------------------------------------------------------------
# normalize_hl7
# ---------------------------------------------------------------------------

def test_normalize_hl7_crlf():
    assert "\r\n" not in normalize_hl7("MSH|...\r\nPID|...\r\n")

def test_normalize_hl7_cr_only():
    result = normalize_hl7("MSH|...\rPID|...\r")
    assert "\r" not in result
    assert "MSH" in result and "PID" in result

def test_normalize_hl7_empty():
    assert normalize_hl7("") == ""

def test_normalize_hl7_none_safe():
    # Should not raise; returns empty string
    assert normalize_hl7(None) == ""


# ---------------------------------------------------------------------------
# get_hl7_message_type
# ---------------------------------------------------------------------------

def test_get_message_type_adt():
    assert get_hl7_message_type(ADT_A01) == "ADT^A01"

def test_get_message_type_oru():
    assert get_hl7_message_type(ORU_R01) == "ORU^R01"

def test_get_message_type_missing_msh():
    assert get_hl7_message_type("PID|1||12345") == ""

def test_get_message_type_empty():
    assert get_hl7_message_type("") == ""


# ---------------------------------------------------------------------------
# redact_hl7_basic
# ---------------------------------------------------------------------------

def test_redaction_masks_pid_name():
    red = redact_hl7_basic(ADT_A01)
    assert "DOE^JOHN" not in red

def test_redaction_masks_pid_dob():
    red = redact_hl7_basic(ADT_A01)
    assert "19800101" not in red

def test_redaction_masks_pid_address():
    red = redact_hl7_basic(ADT_A01)
    assert "123 MAIN ST" not in red

def test_redaction_preserves_msh():
    red = redact_hl7_basic(ADT_A01)
    assert "MSH" in red
    assert "ADT^A01" in red

def test_redaction_preserves_pv1():
    red = redact_hl7_basic(ADT_A01)
    assert "PV1" in red

def test_redaction_non_pid_unchanged():
    msg = "MSH|^~\\&|APP|FAC|R|F|20250101||ADT^A01|001|P|2.3\n"
    assert redact_hl7_basic(msg) == msg


# ---------------------------------------------------------------------------
# parse_hl7
# ---------------------------------------------------------------------------

def test_parse_hl7_returns_dict():
    segs = parse_hl7(ADT_A01)
    assert "MSH" in segs
    assert "PID" in segs
    assert "PV1" in segs

def test_parse_hl7_msh_fields():
    segs = parse_hl7(ADT_A01)
    msh = segs["MSH"][0]
    assert msh[8] == "ADT^A01"

def test_parse_hl7_skips_blank_lines():
    segs = parse_hl7("MSH|^~\\&|A|B|C|D|20250101||ADT^A01|001|P|2.3\n\nPID|1||999\n")
    assert "MSH" in segs
    assert "PID" in segs


# ---------------------------------------------------------------------------
# validate_hl7_message
# ---------------------------------------------------------------------------

def test_validate_adt_valid():
    errors, warnings = validate_hl7_message(ADT_A01)
    assert errors == []

def test_validate_missing_msh():
    errors, _ = validate_hl7_message("PID|1||12345\n")
    assert any("MSH" in e for e in errors)

def test_validate_missing_pid_for_adt():
    msg = "MSH|^~\\&|A|B|C|D|20250101||ADT^A01|001|P|2.3\nPV1|1|I\n"
    errors, _ = validate_hl7_message(msg)
    assert any("PID" in e for e in errors)

def test_validate_missing_pid3():
    msg = "MSH|^~\\&|A|B|C|D|20250101||ADT^A01|001|P|2.3\nPID|1||\nPV1|1|I\n"
    errors, _ = validate_hl7_message(msg)
    assert any("PID-3" in e for e in errors)

def test_validate_missing_pv1_produces_warning():
    msg = "MSH|^~\\&|A|B|C|D|20250101||ADT^A01|001|P|2.3\nPID|1||12345\n"
    errors, warnings = validate_hl7_message(msg)
    assert errors == []
    assert any("PV1" in w for w in warnings)


# ---------------------------------------------------------------------------
# extract_hl7_summary
# ---------------------------------------------------------------------------

def test_summary_message_type():
    s = extract_hl7_summary(ADT_A01)
    assert s["message_type"] == "ADT^A01"

def test_summary_patient_id():
    s = extract_hl7_summary(ADT_A01)
    assert "12345" in s["patient_id"]

def test_summary_encounter_present():
    s = extract_hl7_summary(ADT_A01)
    assert s["encounter_present"] is True

def test_summary_patient_class():
    s = extract_hl7_summary(ADT_A01)
    assert s["patient_class"] == "I"

def test_summary_event_time_14char():
    msg = "MSH|^~\\&|A|B|C|D|20251218120000||ADT^A01|001|P|2.3\nPID|1||123\n"
    s = extract_hl7_summary(msg)
    assert s["event_time"] is not None
    assert s["event_time"].year == 2025

def test_summary_event_time_12char():
    """12-char HL7 datetime (YYYYMMDDHHMM) was previously silently dropped."""
    msg = "MSH|^~\\&|A|B|C|D|202512181200||ADT^A01|001|P|2.3\nPID|1||123\n"
    s = extract_hl7_summary(msg)
    assert s["event_time"] is not None
    assert s["event_time"].month == 12

def test_summary_empty_string():
    s = extract_hl7_summary("")
    assert s["message_type"] == ""
    assert s["event_time"] is None


# ---------------------------------------------------------------------------
# hl7_to_fhir_patient
# ---------------------------------------------------------------------------

def test_patient_resource_type():
    segs = parse_hl7(ADT_A01)
    p = hl7_to_fhir_patient(segs)
    assert p["resourceType"] == "Patient"

def test_patient_id():
    segs = parse_hl7(ADT_A01)
    p = hl7_to_fhir_patient(segs)
    assert p["id"] == "12345"

def test_patient_name():
    segs = parse_hl7(ADT_A01)
    p = hl7_to_fhir_patient(segs)
    name = p["name"][0]
    assert name["family"] == "DOE"
    assert "JOHN" in name["given"]

def test_patient_gender():
    segs = parse_hl7(ADT_A01)
    p = hl7_to_fhir_patient(segs)
    assert p["gender"] == "male"

def test_patient_birth_date():
    segs = parse_hl7(ADT_A01)
    p = hl7_to_fhir_patient(segs)
    assert p["birthDate"] == "1980-01-01"

def test_patient_birth_date_short_raw():
    """Short/malformed birth_raw must not produce malformed date string."""
    msg = "MSH|^~\\&|A|B|C|D|20250101||ADT^A01|001|P|2.3\nPID|1||999^^^MRN||DOE^JANE||198|F\n"
    segs = parse_hl7(msg)
    p = hl7_to_fhir_patient(segs)
    assert p["birthDate"] is None  # "198" is < 8 chars, must not produce "198--"

def test_patient_no_pid_returns_none():
    segs = parse_hl7("MSH|^~\\&|A|B|C|D|20250101||ADT^A01|001|P|2.3\n")
    assert hl7_to_fhir_patient(segs) is None


# ---------------------------------------------------------------------------
# hl7_to_fhir_encounter
# ---------------------------------------------------------------------------

def test_encounter_resource_type():
    segs = parse_hl7(ADT_A01)
    e = hl7_to_fhir_encounter(segs, patient_id="12345")
    assert e["resourceType"] == "Encounter"

def test_encounter_class_inpatient():
    segs = parse_hl7(ADT_A01)
    e = hl7_to_fhir_encounter(segs)
    assert e["class"]["code"] == "IMP"

def test_encounter_class_outpatient():
    segs = parse_hl7(ADT_A01_SHORT_TS)
    e = hl7_to_fhir_encounter(segs)
    assert e["class"]["code"] == "AMB"

def test_encounter_subject_reference():
    segs = parse_hl7(ADT_A01)
    e = hl7_to_fhir_encounter(segs, patient_id="12345")
    assert e["subject"]["reference"] == "Patient/12345"

def test_encounter_no_pv1_returns_none():
    segs = parse_hl7("MSH|^~\\&|A|B|C|D|20250101||ADT^A01|001|P|2.3\nPID|1||999\n")
    assert hl7_to_fhir_encounter(segs) is None


# ---------------------------------------------------------------------------
# hl7_to_all — ADT
# ---------------------------------------------------------------------------

def test_hl7_to_all_adt_keys():
    result = hl7_to_all(ADT_A01)
    assert "patient" in result
    assert "encounter" in result
    assert "x12_837" in result
    assert "x12_835" in result
    assert "claim_reconciliation" in result

def test_hl7_to_all_adt_no_error_key():
    result = hl7_to_all(ADT_A01)
    assert "error" not in result

def test_hl7_to_all_missing_msh9():
    msg = "MSH|^~\\&|A|B|C|D|20250101|||001|P|2.3\nPID|1||999\n"
    result = hl7_to_all(msg)
    assert "error" in result

def test_hl7_to_all_unsupported_type():
    msg = "MSH|^~\\&|A|B|C|D|20250101||SIU^S12|001|P|2.3\nPID|1||999\n"
    result = hl7_to_all(msg)
    assert "error" in result


# ---------------------------------------------------------------------------
# hl7_to_all — ORU
# ---------------------------------------------------------------------------

def test_hl7_to_all_oru_returns_report():
    result = hl7_to_all(ORU_R01)
    assert "report" in result
    assert "observations" in result

def test_hl7_to_all_oru_observation_count():
    result = hl7_to_all(ORU_R01)
    assert len(result["observations"]) == 2


# ---------------------------------------------------------------------------
# hl7_oru_to_fhir
# ---------------------------------------------------------------------------

def test_oru_to_fhir_report_type():
    result = hl7_oru_to_fhir(ORU_R01)
    assert result["report"]["resourceType"] == "DiagnosticReport"

def test_oru_to_fhir_observations():
    result = hl7_oru_to_fhir(ORU_R01)
    obs = result["observations"]
    assert len(obs) == 2
    assert obs[0]["resourceType"] == "Observation"

def test_oru_to_fhir_patient_id():
    result = hl7_oru_to_fhir(ORU_R01)
    assert result["patient_id"] == "67890^^^MRN"


# ---------------------------------------------------------------------------
# X12 837 / 835 / reconciliation
# ---------------------------------------------------------------------------

def test_837_contains_clm_segment():
    segs = parse_hl7(ADT_A01)
    patient = hl7_to_fhir_patient(segs)
    encounter = hl7_to_fhir_encounter(segs, patient_id="12345")
    x12 = fhir_to_837_claim(patient, encounter)
    assert "CLM*" in x12

def test_837_contains_isa_segment():
    segs = parse_hl7(ADT_A01)
    patient = hl7_to_fhir_patient(segs)
    encounter = hl7_to_fhir_encounter(segs, patient_id="12345")
    x12 = fhir_to_837_claim(patient, encounter)
    assert x12.startswith("ISA*")

def test_835_paid_contains_clp():
    segs = parse_hl7(ADT_A01)
    patient = hl7_to_fhir_patient(segs)
    encounter = hl7_to_fhir_encounter(segs, patient_id="12345")
    x12_837 = fhir_to_837_claim(patient, encounter)
    x12_835 = generate_835_from_837(x12_837, outcome="paid")
    assert "CLP*" in x12_835

def test_835_denied_contains_cas_co45():
    segs = parse_hl7(ADT_A01)
    patient = hl7_to_fhir_patient(segs)
    encounter = hl7_to_fhir_encounter(segs, patient_id="12345")
    x12_837 = fhir_to_837_claim(patient, encounter)
    x12_835 = generate_835_from_837(x12_837, outcome="denied")
    assert "CAS*CO*45" in x12_835

def test_reconciliation_paid():
    segs = parse_hl7(ADT_A01)
    patient = hl7_to_fhir_patient(segs)
    encounter = hl7_to_fhir_encounter(segs, patient_id="12345")
    x12_837 = fhir_to_837_claim(patient, encounter)
    x12_835 = generate_835_from_837(x12_837, outcome="paid")
    rec = reconcile_837_835(x12_837, x12_835)
    assert rec["status"] == "paid"
    assert rec["paid_amount"] > 0
    assert rec["billed_total"] > 0

def test_reconciliation_denied():
    segs = parse_hl7(ADT_A01)
    patient = hl7_to_fhir_patient(segs)
    encounter = hl7_to_fhir_encounter(segs, patient_id="12345")
    x12_837 = fhir_to_837_claim(patient, encounter)
    x12_835 = generate_835_from_837(x12_837, outcome="denied")
    rec = reconcile_837_835(x12_837, x12_835)
    assert rec["status"] == "denied"
    assert rec["paid_amount"] == 0.0


# ---------------------------------------------------------------------------
# build_message_profile / build_trigger_event
# ---------------------------------------------------------------------------

def test_message_profile_adt_a01():
    assert "ADT" in build_message_profile("ADT^A01")
    assert "Admission" in build_message_profile("ADT^A01")

def test_message_profile_oru_r01():
    assert "ORU" in build_message_profile("ORU^R01")

def test_message_profile_unknown():
    profile = build_message_profile("")
    assert "Unknown" in profile

def test_trigger_event_adt_a03():
    evt = build_trigger_event("ADT^A03")
    assert evt["code"] == "A03"
    assert "Discharge" in evt["description"]

def test_trigger_event_oru_r01():
    evt = build_trigger_event("ORU^R01")
    assert evt["code"] == "R01"

def test_trigger_event_unknown_type():
    evt = build_trigger_event("XYZ^Z99")
    assert evt["code"] == "Z99"
