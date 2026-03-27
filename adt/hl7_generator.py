"""
hl7_generator.py
~~~~~~~~~~~~~~~~
Generates standards-compliant HL7 v2.3 ADT messages for A01, A02, A03, A08
event types without any third-party HL7 library dependency.

Segment layout per event:
  A01 (Admit)     – MSH · EVN · PID · PV1
  A02 (Transfer)  – MSH · EVN · PID · PV1
  A03 (Discharge) – MSH · EVN · PID · PV1
  A08 (Update)    – MSH · EVN · PID · PV1 (minimal PV1)

All field values are synthetic/demo-safe (no real PHI).
"""

import random
import string
from datetime import datetime, timezone

# ── Segment delimiter ─────────────────────────────────────────────────────────
SEG_SEP = "\r"   # HL7 segment terminator (CR, not CRLF)

# ── Static lookup tables ──────────────────────────────────────────────────────
_FIRST_NAMES = ["James", "Maria", "David", "Sarah", "Michael", "Emily",
                 "Robert", "Jessica", "William", "Linda"]
_LAST_NAMES  = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
                 "Miller", "Davis", "Wilson", "Taylor"]
_LOCATIONS   = {
    "A01": ["ED^001^A", "ICU^204^B", "MED^310^C", "SURG^412^D"],
    "A02": ["ICU^204^B", "MED^310^C", "REHAB^501^A", "SURG^412^D"],
    "A03": ["ED^001^A", "MED^310^C"],
    "A08": [""],
}
_DOCTORS = [
    "1234^Adams^John",
    "5678^Brown^Lisa",
    "9012^Carter^Michael",
    "3456^Davis^Susan",
]
_ADMIT_SOURCES = {"A01": "7", "A02": "1", "A03": "1", "A08": ""}
_DISCHARGE_DISP = {"A01": "", "A02": "", "A03": "01", "A08": ""}


def _now_hl7(dt: datetime | None = None) -> str:
    """Return HL7-formatted timestamp: YYYYMMDDHHMMSS."""
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%Y%m%d%H%M%S")


def _msg_control_id() -> str:
    """Generate a short random message control ID."""
    return "MSG" + "".join(random.choices(string.digits, k=8))


def _random_dob() -> str:
    year  = random.randint(1940, 2000)
    month = random.randint(1, 12)
    day   = random.randint(1, 28)
    return f"{year:04d}{month:02d}{day:02d}"


def _random_name() -> tuple[str, str]:
    return random.choice(_LAST_NAMES), random.choice(_FIRST_NAMES)


def _msh(event_type: str, msg_ctrl_id: str, ts: str) -> str:
    """MSH – Message Header segment."""
    return (
        f"MSH|^~\\&"
        f"|SendingApp|DemoHospital"
        f"|ReceivingApp|ReceivingFacility"
        f"|{ts}"
        f"||ADT^{event_type}"
        f"|{msg_ctrl_id}"
        f"|P|2.3"
    )


def _evn(event_type: str, ts: str) -> str:
    """EVN – Event Type segment."""
    return f"EVN|{event_type}|{ts}"


def _pid(patient_id: str) -> str:
    """PID – Patient Identification segment."""
    last, first = _random_name()
    dob    = _random_dob()
    gender = random.choice(["M", "F"])
    street_num = random.randint(100, 9999)
    zip_code   = "".join(random.choices(string.digits, k=5))
    return (
        f"PID|1"
        f"||{patient_id}^^^DemoHospital^MR"
        f"||{last}^{first}||{dob}|{gender}"
        f"|||{street_num} Demo St^^Springfield^IL^{zip_code}"
        f"|||||||{patient_id}"
    )


def _pv1(event_type: str) -> str:
    """PV1 – Patient Visit segment."""
    location     = random.choice(_LOCATIONS.get(event_type, [""])  )
    doctor       = random.choice(_DOCTORS)
    admit_src    = _ADMIT_SOURCES.get(event_type, "")
    disc_disp    = _DISCHARGE_DISP.get(event_type, "")
    patient_class = "E" if event_type == "A01" and "ED" in location else "I"
    return (
        f"PV1|1"
        f"|{patient_class}"
        f"|{location}"
        f"|||{doctor}"
        f"||||||{admit_src}"
        f"|||||||||||||||||||||||||||{disc_disp}"
    )


# ── Public API ────────────────────────────────────────────────────────────────

def generate_adt(patient_id: str, event_type: str) -> str:
    """
    Build a complete HL7 v2.3 ADT message string for the given event type.

    Parameters
    ----------
    patient_id : str
        Medical Record Number (MRN) for the patient.
    event_type : str
        One of: "A01", "A02", "A03", "A08".

    Returns
    -------
    str
        HL7 v2.3 message with CR-terminated segments.

    Raises
    ------
    ValueError
        If event_type is not one of the supported values.
    """
    event_type = event_type.upper()
    supported = {"A01", "A02", "A03", "A08"}
    if event_type not in supported:
        raise ValueError(f"Unsupported event type '{event_type}'. Choose from {supported}.")

    ts          = _now_hl7()
    msg_ctrl_id = _msg_control_id()

    segments = [
        _msh(event_type, msg_ctrl_id, ts),
        _evn(event_type, ts),
        _pid(patient_id),
        _pv1(event_type),
    ]
    return SEG_SEP.join(segments) + SEG_SEP
