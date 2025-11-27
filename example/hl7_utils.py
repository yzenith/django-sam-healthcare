# app/hl7_utils.py
from datetime import datetime

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


def hl7_to_all(hl7_text: str):
    segments = parse_hl7(hl7_text)
    patient = hl7_to_fhir_patient(segments)
    encounter = hl7_to_fhir_encounter(segments, patient_id=(patient or {}).get("id"))
    x12 = fhir_to_837_claim(patient, encounter) if patient and encounter else ""

    return {
        "patient": patient,
        "encounter": encounter,
        "x12_837": x12
    }
