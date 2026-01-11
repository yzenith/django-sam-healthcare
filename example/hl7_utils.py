# app/hl7_utils.py
from datetime import datetime

ADT_EVENT_LABELS = {
    "A01": "Admission (Inpatient/ER → Admit)",
    "A02": "Transfer (Bed/Unit Change)",
    "A03": "Discharge",
    "A04": "Registration (Outpatient/ER)",
    "A08": "Update Patient Info",
}

ORU_EVENT_LABELS = {
    "R01": "Lab Result (Observation Report)",
}

ADT_EVENT_REASON = {
    "A01": "Start inpatient workflow: care coordination + billing",
    "A03": "Close encounter: discharge workflow + billing finalization",
    "A08": "Update demographics/visit data; downstream reconciliation",
}

ORU_EVENT_REASON = {
    "R01": "Publish lab results: clinical review + charge capture",
}

def build_trigger_event(message_type: str) -> dict:
    parts = (message_type or "").split("^")
    msg = parts[0] if len(parts) > 0 else ""
    evt = parts[1] if len(parts) > 1 else ""

    if msg == "ADT":
        return {
            "code": evt,
            "description": ADT_EVENT_LABELS.get(evt, f"ADT Event {evt or '(unknown)'}"),
            "business_reason": ADT_EVENT_REASON.get(evt, ""),
        }
    if msg == "ORU":
        return {
            "code": evt,
            "description": ORU_EVENT_LABELS.get(evt, f"ORU Event {evt or '(unknown)'}"),
            "business_reason": ORU_EVENT_REASON.get(evt, ""),
        }
    return {"code": evt, "description": "", "business_reason": ""}

def build_message_profile(message_type: str) -> str:
    """
    Return something a hiring manager expects:
    'HL7 v2 ADT (Admission)' not just 'ADT^A01'
    """
    if not message_type:
        return "HL7 v2 (Unknown)"

    parts = message_type.split("^")
    msg = parts[0] if len(parts) > 0 else ""
    evt = parts[1] if len(parts) > 1 else ""

    if msg == "ADT":
        label = ADT_EVENT_LABELS.get(evt, f"ADT Event {evt or '(unknown)'}")
        return f"HL7 v2 ADT ({label})"
    if msg == "ORU":
        label = ORU_EVENT_LABELS.get(evt, f"ORU Event {evt or '(unknown)'}")
        return f"HL7 v2 ORU ({label})"

    return f"HL7 v2 {msg} ({evt})" if evt else f"HL7 v2 {msg}"

def hl7_to_all(hl7_text: str):
    lines = hl7_text.strip().split("\n")
    msg_type = None

    # Identify message type from MSH-9
    for segment in lines:
        if segment.startswith("MSH"):
            fields = segment.split("|")
            # MSH-9 is e.g. "ADT^A01" or "ORU^R01"
            msg_type = fields[8] if len(fields) > 8 else None
            break

    if not msg_type:
        return {
            "error": "Unable to determine HL7 message type (MSH-9 missing).",
            "raw_hl7": hl7_text,
        }

    # --- ADT messages: build Patient + Encounter + 837 ---
    if msg_type.startswith("ADT"):
        segments = parse_hl7(hl7_text)

        patient = hl7_to_fhir_patient(segments) or {}
        patient_id = (patient.get("identifier") or [{}])[0].get("value") or patient.get("id")

        encounter = hl7_to_fhir_encounter(segments, patient_id=patient_id)
        x12_837 = None
        # if patient and encounter:
        #     x12_837 = fhir_to_837_claim(patient, encounter)

        # return {
        #     "message_type": msg_type,
        #     "raw_hl7": hl7_text,
        #     "patient": patient,
        #     "encounter": encounter,
        #     "x12_837": x12_837,
        # }

        x12_835 = None
        claim_reconciliation = None

        if patient and encounter:
            x12_837 = fhir_to_837_claim(patient, encounter)
            # demo: choose "paid" by default; later you can toggle by query param or payload field
            x12_835 = generate_835_from_837(x12_837, outcome="paid")
            claim_reconciliation = reconcile_837_835(x12_837, x12_835)

        return {
            "message_type": msg_type,
            "raw_hl7": hl7_text,
            "patient": patient,
            "encounter": encounter,
            "x12_837": x12_837,
            "x12_835": x12_835,
            "claim_reconciliation": claim_reconciliation,
        }


    # --- ORU messages: reuse your existing ORU converter ---
    if msg_type.startswith("ORU"):
        result = hl7_oru_to_fhir(hl7_text)
        # result already includes message_type="ORU^R01" etc.
        return result

    # --- Unsupported / future types ---
    return {
        "error": f"Unsupported HL7 message type: {msg_type}",
        "message_type": msg_type,
        "raw_hl7": hl7_text,
    }

def extract_hl7_summary(hl7_text: str) -> dict:
    """
    Extract analyst-friendly summary fields from an HL7 message.
    This is NOT a full parser – it is designed for triage & support use.
    """

    summary = {
        "message_type": "",
        "patient_id": "",
        "patient_class": "",
        "encounter_present": False,
        "event_time": None,
    }

    if not hl7_text:
        return summary

    # Normalize line breaks
    hl7_text = hl7_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [l for l in hl7_text.split("\n") if l.strip()]

    for line in lines:
        fields = line.split("|")
        segment = fields[0]

        # MSH|^~\&|...|ADT^A01|...
        if segment == "MSH" and len(fields) > 8:
            summary["message_type"] = fields[8]

            # MSH-7: Message Date/Time
            if len(fields) > 6 and fields[6]:
                try:
                    summary["event_time"] = datetime.strptime(fields[6], "%Y%m%d%H%M%S")
                except ValueError:
                    pass

        # PID|...|PID-3 Patient Identifier
        elif segment == "PID":
            if len(fields) > 3:
                summary["patient_id"] = fields[3]

        # PV1|...|PV1-2 Patient Class
        elif segment == "PV1":
            summary["encounter_present"] = True
            if len(fields) > 2:
                summary["patient_class"] = fields[2]

            # PV1-44 Admit Date/Time (preferred over MSH-7 if present)
            if len(fields) > 44 and fields[44]:
                try:
                    summary["event_time"] = datetime.strptime(fields[44], "%Y%m%d%H%M%S")
                except ValueError:
                    pass

    return summary

# example/hl7_utils.py
def extract_source_context_from_msh(hl7_text: str) -> dict:
    """
    Pull basic 'who sent it' context from MSH.
    MSH-3 Sending Application
    MSH-4 Sending Facility
    MSH-9 Message Type (e.g. ADT^A01)
    """
    ctx = {
        "standard": "HL7 v2",
        "interface_type": "",          # e.g. "ADT"
        "sending_application": "",
        "sending_facility": "",
    }

    if not hl7_text:
        return ctx

    hl7_text = hl7_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [l for l in hl7_text.split("\n") if l.strip()]
    msh = next((l for l in lines if l.startswith("MSH")), "")
    if not msh:
        return ctx

    fields = msh.split("|")
    # MSH segment indexes:
    # [2]=MSH-3, [3]=MSH-4, [8]=MSH-9
    if len(fields) > 2:
        ctx["sending_application"] = fields[2]
    if len(fields) > 3:
        ctx["sending_facility"] = fields[3]
    if len(fields) > 8:
        msg_type = fields[8]  # ADT^A01
        ctx["interface_type"] = (msg_type.split("^", 1)[0] if msg_type else "")

    return ctx



def validate_hl7_message(hl7_text: str):
    errors, warnings = [], []
    if not hl7_text.strip().startswith("MSH"):
        errors.append("Missing MSH segment (message must start with MSH)")
        return errors, warnings

    segments = parse_hl7(hl7_text)
    msh = (segments.get("MSH") or [["MSH"]])[0]
    msg_type = msh[8] if len(msh) > 8 else ""
    if not msg_type:
        errors.append("Missing MSH-9 (message type)")

    if msg_type.startswith("ADT"):
        if "PID" not in segments:
            errors.append("ADT requires PID segment")
        else:
            pid = segments["PID"][0]
            pid3 = pid[3] if len(pid) > 3 else ""
            if not pid3:
                errors.append("Missing PID-3 (Patient Identifier)")
        if "PV1" not in segments:
            warnings.append("Missing PV1 segment (Encounter will not be generated)")

    return errors, warnings



def parse_hl7(hl7_text: str):
    """
    把 HL7 文本解析成:
    {
      "MSH": [ [fields...], ... ],
      "PID": [ [fields...], ... ],
      "PV1": [ [fields...], ... ],
      ...
    }
    """
    segments = {}
    for line in hl7_text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split('|')
        name = parts[0]
        segments.setdefault(name, []).append(parts)
    return segments


def hl7_to_fhir_patient(segments):
    """
    只处理第一个 PID 段
    """
    pid_list = segments.get("PID")
    if not pid_list:
        return None

    pid = pid_list[0]

    # 安全取字段
    def get(field_index):
        return pid[field_index] if len(pid) > field_index else ""

    # PID-3 Patient Identifier List
    pid3 = get(3)
    pid3_components = pid3.split('^') if pid3 else []
    patient_id = pid3_components[0] if pid3_components else ""

    # PID-5 Patient Name
    pid5 = get(5)
    name_components = pid5.split('^') if pid5 else []
    family = name_components[0] if len(name_components) > 0 else ""
    given = name_components[1] if len(name_components) > 1 else ""

    # PID-7 Birth Date
    birth_raw = get(7)
    birth_date = None
    if birth_raw:
        # YYYYMMDD -> YYYY-MM-DD
        birth_date = f"{birth_raw[0:4]}-{birth_raw[4:6]}-{birth_raw[6:8]}"

    # PID-8 Gender
    gender_raw = get(8)
    gender_map = {"M": "male", "F": "female"}
    gender = gender_map.get(gender_raw, "unknown")

    # PID-11 Address
    addr_raw = get(11)
    addr_comp = addr_raw.split('^') if addr_raw else []
    line1 = addr_comp[0] if len(addr_comp) > 0 else ""
    city = addr_comp[2] if len(addr_comp) > 2 else ""
    state = addr_comp[3] if len(addr_comp) > 3 else ""
    postal = addr_comp[4] if len(addr_comp) > 4 else ""

    patient = {
        "resourceType": "Patient",
        "id": patient_id or None,
        "identifier": [
            {
                "system": "urn:example:hospital-mrn",
                "value": patient_id
            }
        ] if patient_id else [],
        "name": [
            {
                "family": family,
                "given": [given] if given else []
            }
        ],
        "gender": gender,
        "birthDate": birth_date,
        "address": [
            {
                "line": [line1] if line1 else [],
                "city": city or None,
                "state": state or None,
                "postalCode": postal or None
            }
        ]
    }

    return patient


def hl7_to_fhir_encounter(segments, patient_id: str = None):
    pv1_list = segments.get("PV1")
    if not pv1_list:
        return None

    pv1 = pv1_list[0]

    def get(field_index):
        return pv1[field_index] if len(pv1) > field_index else ""

    # PV1-2 Patient Class
    cls = get(2)
    # 简单 class mapping
    class_code_map = {
        "I": "IMP",   # inpatient
        "O": "AMB",   # outpatient
        "E": "EMER",  # emergency
    }
    class_code = class_code_map.get(cls, "AMB")

    # PV1-3 Location
    loc_raw = get(3)
    loc_comp = loc_raw.split('^') if loc_raw else []
    loc_display = "^".join(loc_comp) if loc_comp else None

    # PV1-44 Admit Date/Time (YYYYMMDDHHMM)
    admit_raw = get(44)
    start_iso = None
    if admit_raw and len(admit_raw) >= 12:
        dt = datetime.strptime(admit_raw[:12], "%Y%m%d%H%M")
        start_iso = dt.isoformat()

    encounter = {
        "resourceType": "Encounter",
        "status": "in-progress",
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": class_code
        },
        "subject": {
            "reference": f"Patient/{patient_id}"
        } if patient_id else None,
        "period": {
            "start": start_iso
        } if start_iso else {}
    }

    if loc_display:
        encounter["location"] = [
            {
                "location": {
                    "display": loc_display
                }
            }
        ]

    return encounter


def fhir_to_837_claim(patient, encounter):
    """
    用非常简化的方式从 Patient + Encounter 生成一个 837 Claim 文本。
    真正项目会用 diagnosis/procedure 等；这里只展示结构和 mapping 思路。
    """
    patient_id = (patient.get("identifier") or [{}])[0].get("value", "12345")
    claim_id = patient_id  # demo 用病人号当 claim 号
    total = 150  # demo 固定金额

    # 简化：拿 name/address 生成 NM1/N3/N4
    name = (patient.get("name") or [{}])[0]
    family = name.get("family", "")
    given = (name.get("given") or [""])[0]

    addr = (patient.get("address") or [{}])[0]
    line1 = (addr.get("line") or [""])[0]
    city = addr.get("city", "")
    state = addr.get("state", "")
    postal = addr.get("postalCode", "")

    segments = []

    # Header 略简化
    segments.append("ISA*00*          *00*          *ZZ*SENDERID      *ZZ*RECEIVERID    *250101*1200*^*00501*000000001*0*T*:~")
    segments.append("GS*HC*SENDERID*RECEIVERID*20250101*1200*1*X*005010X222A1~")
    segments.append("ST*837*0001*005010X222A1~")
    segments.append("BHT*0019*00*0123*20250102*1200*CH~")

    # Billing Provider（写死）
    segments.append("NM1*85*2*GOOD HEALTH CLINIC*****XX*1234567893~")
    segments.append("N3*123 MAIN ST~")
    segments.append("N4*DALLAS*TX*75001~")

    # Subscriber/Patient
    segments.append("HL*1**20*1~")
    segments.append("HL*2*1*22*0~")
    segments.append("SBR*P*18*******MC~")
    segments.append(f"NM1*IL*1*{family}*{given}****MI*{patient_id}~")
    segments.append(f"N3*{line1}~")
    segments.append(f"N4*{city}*{state}*{postal}~")

    # Claim (CLM)
    segments.append(f"CLM*{claim_id}*{total}***11:B:1*Y*A*Y*Y~")

    # Demo: 只有一个服务行
    segments.append("LX*1~")
    segments.append("SV1*HC:99213*150*UN*1***1~")

    segments.append("SE*12*0001~")
    segments.append("GE*1*1~")
    segments.append("IEA*1*000000001~")

    return "\n".join(segments)


def hl7_oru_to_fhir(hl7_text: str) -> dict:
    """
    Convert a simple HL7 ORU^R01 lab result message into:
      - FHIR DiagnosticReport
      - list[FHIR Observation]
    """

    # ✅ handle \r, \n, or both
    segments_raw = [
        line.strip()
        for line in hl7_text.strip().splitlines()
        if line.strip()
    ]

    # --- get message type from MSH-9 if present ---
    msg_type = "ORU^R01"
    for seg in segments_raw:
        if seg.startswith("MSH"):
            fields = seg.split("|")
            if len(fields) > 8 and fields[8]:
                msg_type = fields[8]
            break

    pid = {}
    obr = {}
    obx_list = []

    for seg in segments_raw:
        fields = seg.split("|")

        # PID
        if seg.startswith("PID"):
            patient_id = fields[3] if len(fields) > 3 else ""
            name_field = fields[5] if len(fields) > 5 else ""
            dob = fields[7] if len(fields) > 7 else ""
            sex = fields[8] if len(fields) > 8 else ""

            family = ""
            given = ""
            if name_field:
                comps = name_field.split("^")
                family = comps[0] if len(comps) > 0 else ""
                given = comps[1] if len(comps) > 1 else ""

            pid = {
                "id": patient_id,
                "name": {
                    "family": family,
                    "given": given,
                },
                "dob": dob,
                "sex": sex,
            }

        # OBR
        if seg.startswith("OBR"):
            code_field = fields[4] if len(fields) > 4 else ""
            code = ""
            desc = ""
            if code_field:
                parts = code_field.split("^")
                code = parts[0] if len(parts) > 0 else ""
                desc = parts[1] if len(parts) > 1 else ""

            date = fields[7] if len(fields) > 7 else ""

            obr = {
                "id": fields[3] if len(fields) > 3 else "",
                "code": code,
                "description": desc,
                "date": date,
            }

        # OBX
        if seg.startswith("OBX"):
            code_field = fields[3] if len(fields) > 3 else ""
            code = ""
            desc = ""
            if code_field:
                parts = code_field.split("^")
                code = parts[0] if len(parts) > 0 else ""
                desc = parts[1] if len(parts) > 1 else ""

            obx = {
                "id": fields[1] if len(fields) > 1 else "",
                "type": fields[2] if len(fields) > 2 else "",
                "code": code,
                "description": desc,
                "value": fields[5] if len(fields) > 5 else "",
                "unit": fields[6] if len(fields) > 6 else "",
                "ref_range": fields[7] if len(fields) > 7 else "",
                "abnormal": fields[8] if len(fields) > 8 else None,
            }
            obx_list.append(obx)

    patient_id = pid.get("id")

    # --- Build FHIR Observations ---
    fhir_observations = []
    for idx, obx in enumerate(obx_list, start=1):
        obs = {
            "resourceType": "Observation",
            "id": f"obx-{idx}",
            "status": "final",
            "code": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": obx["code"],
                        "display": obx["description"],
                    }
                ]
            },
            "valueString": obx["value"],
        }

        if obx.get("unit") or obx.get("ref_range"):
            obs["note"] = [{
                "text": f"Unit: {obx.get('unit', '')}  RefRange: {obx.get('ref_range', '')}"
            }]

        if patient_id:
            obs["subject"] = {"reference": f"Patient/{patient_id}"}

        if obr.get("date"):
            obs["effectiveDateTime"] = obr["date"]

        fhir_observations.append(obs)

    # --- Build DiagnosticReport ---
    diagnostic_report = {
        "resourceType": "DiagnosticReport",
        "status": "final",
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": obr.get("code"),
                    "display": obr.get("description"),
                }
            ]
        },
        "result": [
            {"reference": f"Observation/obx-{i+1}"}
            for i in range(len(fhir_observations))
        ],
    }

    if patient_id:
        diagnostic_report["subject"] = {"reference": f"Patient/{patient_id}"}

    if obr.get("date"):
        diagnostic_report["effectiveDateTime"] = obr["date"]

    return {
        "message_type": msg_type,
        "raw_hl7": hl7_text,
        "patient_id": patient_id,
        "report": diagnostic_report,
        "observations": fhir_observations,
    }

def parse_837_basic(x12_837: str) -> dict:
    """
    Extract minimal claim info from the CLM segment.
    Returns: {"claim_id": "...", "billed_total": 150.0}
    """
    if not x12_837:
        return {}

    # Split by segment terminator
    segments = [s.strip() for s in x12_837.replace("\n", "").split("~") if s.strip()]
    clm = next((s for s in segments if s.startswith("CLM*")), None)
    if not clm:
        return {}

    parts = clm.split("*")
    # CLM*{claim_id}*{total}***...
    claim_id = parts[1] if len(parts) > 1 else ""
    billed_total = float(parts[2]) if len(parts) > 2 and parts[2] else 0.0

    return {"claim_id": claim_id, "billed_total": billed_total}


def generate_835_from_837(x12_837: str, outcome: str = "paid") -> str:
    """
    Create a simplified 835 ERA from an 837 (demo-quality but structurally realistic).

    outcome:
      - "paid": partial payment + patient responsibility
      - "denied": denial with adjustment reason
    """
    info = parse_837_basic(x12_837)
    claim_id = info.get("claim_id", "UNKNOWN")
    billed_total = float(info.get("billed_total", 0.0))

    if outcome not in ("paid", "denied"):
        outcome = "paid"

    if outcome == "paid":
        paid = round(billed_total * 0.8, 2)
        patient_resp = round(billed_total - paid, 2)
        clp_status = "1"  # processed as primary, paid
        cas = f"CAS*PR*1*{patient_resp:.2f}~" if patient_resp > 0 else ""
    else:
        paid = 0.0
        patient_resp = 0.0
        clp_status = "4"  # denied
        # CO-45 is a common demo denial/adjustment reason used in examples
        cas = f"CAS*CO*45*{billed_total:.2f}~"

    segments = []
    segments.append("ISA*00*          *00*          *ZZ*SENDERID      *ZZ*RECEIVERID    *250101*1200*^*00501*000000905*0*T*:~")
    segments.append("GS*HP*SENDERID*RECEIVERID*20250101*1200*1*X*005010X221A1~")
    segments.append("ST*835*0001~")
    segments.append("BPR*I*0*C*CHK************20250101~")
    segments.append("TRN*1*12345*9876543210~")
    segments.append("N1*PR*DEMO PAYER*PI*99999~")
    segments.append("N1*PE*GOOD HEALTH CLINIC*XX*1234567893~")

    # CLP*{patient_control_number}*{status}*{total}*{paid}*{patient_resp}*MC*{payer_claim_control}*11~
    segments.append(f"CLP*{claim_id}*{clp_status}*{billed_total:.2f}*{paid:.2f}*{patient_resp:.2f}*MC*PCN123*11~")
    if cas:
        segments.append(cas)

    segments.append("SE*9*0001~")
    segments.append("GE*1*1~")
    segments.append("IEA*1*000000905~")

    return "\n".join(segments)


def reconcile_837_835(x12_837: str, x12_835: str) -> dict:
    """
    Produce a reconciliation summary: billed vs paid vs patient responsibility.
    """
    s_info = parse_837_basic(x12_837)
    billed_total = float(s_info.get("billed_total", 0.0))
    claim_id = s_info.get("claim_id", "")

    paid = 0.0
    patient_resp = 0.0
    status = "unknown"
    adjustments = []

    if x12_835:
        segments = [s.strip() for s in x12_835.replace("\n", "").split("~") if s.strip()]
        clp = next((s for s in segments if s.startswith("CLP*")), None)
        if clp:
            parts = clp.split("*")
            # CLP*claimId*status*billed*paid*patientResp*...
            status_code = parts[2] if len(parts) > 2 else ""
            billed_from_835 = float(parts[3]) if len(parts) > 3 and parts[3] else billed_total
            paid = float(parts[4]) if len(parts) > 4 and parts[4] else 0.0
            patient_resp = float(parts[5]) if len(parts) > 5 and parts[5] else 0.0
            billed_total = billed_from_835

            status = "paid" if status_code == "1" else ("denied" if status_code == "4" else "other")

        # collect CAS adjustments
        for cas in [s for s in segments if s.startswith("CAS*")]:
            adjustments.append(cas)

    return {
        "claim_id": claim_id,
        "status": status,
        "billed_total": round(billed_total, 2),
        "paid_amount": round(paid, 2),
        "patient_responsibility": round(patient_resp, 2),
        "adjustments": adjustments,
        "balance_due_to_provider": round(max(billed_total - paid - patient_resp, 0.0), 2),
    }

