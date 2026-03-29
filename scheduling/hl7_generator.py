"""
scheduling/hl7_generator.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Generates HL7 v2.3 SIU (Scheduling Information Unsolicited) messages.

Supported trigger events
------------------------
S12 – New appointment booking
S14 – Appointment modification (reschedule, location change, provider change)
S15 – Appointment cancellation

Segments generated
------------------
MSH  – Message Header
SCH  – Scheduling Activity Information
PID  – Patient Identification
PV1  – Patient Visit (limited — location / provider)
RGS  – Resource Group (filler)
AIS  – Appointment Information — Service
AIL  – Appointment Information — Location
AIP  – Appointment Information — Personnel (provider)
"""

import random
import string
from datetime import datetime, timedelta
from dataclasses import dataclass

CR = "\r"

_APPOINTMENT_TYPES = {
    "ROUTINE":    "ROUTINE^Routine^HL70276",
    "URGENT":     "URGENT^Urgent^HL70276",
    "WALK_IN":    "WALKIN^Walk-in^HL70276",
    "FOLLOW_UP":  "FOLLOWUP^Follow-up^HL70276",
    "TELEHEALTH": "TELEMEDICINE^Telemedicine^HL70276",
}

_REASON_CODES = {
    "Annual physical":       "Z00.00",
    "Follow-up visit":       "Z09",
    "Chest pain":            "R07.9",
    "Diabetes management":   "E11.9",
    "Hypertension review":   "I10",
    "Medication review":     "Z79.899",
    "Lab result review":     "Z00.01",
    "Pre-operative consult": "Z01.818",
}


def _msg_id() -> str:
    return "SIU-" + "".join(random.choices(string.digits, k=8))


def _now_ts() -> str:
    return datetime.utcnow().strftime("%Y%m%d%H%M%S")


def generate_siu(
    patient_id: str,
    event_type: str,
    appointment_id: str,
    appointment_dt: datetime,
    duration_minutes: int = 30,
    appointment_type: str = "ROUTINE",
    provider_id: str = "",
    provider_name: str = "",
    location: str = "",
    reason: str = "",
    note: str = "",
) -> str:
    """
    Build a CR-terminated HL7 v2.3 SIU message string.

    Returns the raw HL7 string (segments joined by CR).
    """
    now        = _now_ts()
    appt_start = appointment_dt.strftime("%Y%m%d%H%M%S")
    appt_end   = (appointment_dt + timedelta(minutes=duration_minutes)).strftime("%Y%m%d%H%M%S")
    msg_id     = _msg_id()
    appt_type  = _APPOINTMENT_TYPES.get(appointment_type, _APPOINTMENT_TYPES["ROUTINE"])
    prov       = provider_id   or f"PROV-{random.randint(100,999)}"
    prov_name  = provider_name or "Demo Provider"
    loc        = location      or f"CLINIC-{random.randint(1,5)}"
    rsn        = reason        or random.choice(list(_REASON_CODES.keys()))

    # status code for S14/S15 differs from S12
    placer_status = {
        "S12": "Booked",
        "S14": "Modified",
        "S15": "Cancelled",
    }.get(event_type, "Booked")

    seg_msh = (
        f"MSH|^~\\&|SCHEDULING|FAC1|EHR|FAC1|{now}||SIU^{event_type}|{msg_id}|P|2.3"
    )
    seg_sch = (
        f"SCH"
        f"|{appointment_id}"          # SCH-1 Placer appointment ID
        f"|{appointment_id}-F"        # SCH-2 Filler appointment ID
        f"|||"                        # SCH-3/4/5
        f"|{appt_type}"              # SCH-6 Appointment type
        f"|{duration_minutes}"        # SCH-7 Appointment duration
        f"|min"                       # SCH-8 Duration units
        f"|{appt_start}^{appt_end}"  # SCH-11 Appointment timing
        f"||||"                       # SCH-12..14
        f"|{placer_status}"          # SCH-25 Filler status code
    )
    seg_pid = (
        f"PID"
        f"|1"
        f"||{patient_id}^^^DEMO&1.2.3.4.5&ISO"
        f"|||{prov_name.replace(' ', '^')}"
        f"|||U"
    )
    seg_pv1 = (
        f"PV1"
        f"|1"
        f"|O"                         # outpatient
        f"|{loc}^{loc}^A^FAC1"
        f"||||||{prov}^{prov_name.replace(' ', '^')}"
    )
    seg_rgs = "RGS|1|A"

    seg_ais = (
        f"AIS"
        f"|1"
        f"|A"
        f"|{rsn.replace(' ', '_')}^{rsn}^L"
        f"|{appt_start}"
        f"|{duration_minutes}"
        f"|min"
    )
    seg_ail = (
        f"AIL"
        f"|1"
        f"|A"
        f"|{loc}^{loc}^L"
        f"|||{appt_start}"
        f"|{duration_minutes}"
        f"|min"
    )
    seg_aip = (
        f"AIP"
        f"|1"
        f"|A"
        f"|{prov}^{prov_name.replace(' ', '^')}^L"
        f"|MD"
        f"|{appt_start}"
        f"|{duration_minutes}"
        f"|min"
    )

    return CR.join([
        seg_msh, seg_sch, seg_pid, seg_pv1, seg_rgs, seg_ais, seg_ail, seg_aip,
    ]) + CR
