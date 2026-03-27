"""
dft_generator.py
~~~~~~~~~~~~~~~~
Generates HL7 v2.3 DFT^P03 (Post Detail Financial Transaction) messages.

A DFT^P03 is the billing notification sent by an HIS/EHR to a billing system
after a clinical event creates chargeable services.  Each charge line maps to
one FT1 segment, which in turn maps 1-to-1 with an X12 837 LX/SV1 service line.

Revenue cycle chain:
  ADT^A01 (admit)  → DFT^P03 (room/accommodation charges)
  ADT^A03 (discharge) → DFT^P03 (all professional service charges)

Segment layout:
  MSH  – Message Header
  EVN  – Event Type
  PID  – Patient Identification
  PV1  – Patient Visit (encounter context)
  FT1  – Financial Transaction (one per charge line)
"""

import random
import string
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

SEG_SEP = "\r"

# ── Charge catalogue by trigger event ─────────────────────────────────────────

_ADMISSION_CHARGES = [
    # (cpt, description, revenue_code, department, unit_price)
    ("0100", "Room & Board – Medical/Surgical",        "0110", "MED",  850.00),
    ("0260", "IV Solutions",                           "0260", "PHAR", 120.00),
    ("0272", "Medical/Surgical Supplies",              "0270", "NURS",  75.00),
]

_DISCHARGE_CHARGES = [
    ("99285", "Emergency Dept Visit – High Complexity",  "0450", "ED",    450.00),
    ("85025",  "Complete Blood Count (CBC)",              "0300", "LAB",    85.00),
    ("71046",  "Chest X-Ray – 2 views",                  "0320", "RAD",   210.00),
    ("96365",  "IV Infusion – Initial",                  "0260", "PHAR",  175.00),
    ("99232",  "Subsequent Hospital Care",               "0120", "MED",   200.00),
]

_MANUAL_CHARGES = [
    ("99213", "Office/Outpatient Visit – Moderate",     "0510", "CLINIC", 150.00),
    ("80053", "Comprehensive Metabolic Panel",          "0300", "LAB",     95.00),
    ("93000", "ECG with Interpretation",                "0730", "CARD",   110.00),
]

_INSURANCE_PLANS = ["BCBS", "AETNA", "CIGNA", "HUMANA", "MEDICAID", "MEDICARE"]


@dataclass
class ChargeItem:
    line_number: int
    charge_id: str
    encounter_id: str
    service_date: date
    transaction_type: str        # CG / CR / PY
    procedure_code: str
    procedure_description: str
    revenue_code: str
    department: str
    unit_amount: Decimal
    quantity: int
    total_amount: Decimal
    insurance_plan: str = "BCBS"


def _now_hl7(dt: datetime | None = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%Y%m%d%H%M%S")


def _msg_id() -> str:
    return "DFT" + "".join(random.choices(string.digits, k=8))


def _charge_id() -> str:
    return "CHG" + "".join(random.choices(string.digits, k=6))


def _encounter_id(patient_id: str) -> str:
    return f"ENC-{patient_id}-{''.join(random.choices(string.digits, k=4))}"


def _build_charges(trigger_event: str, encounter_id: str) -> list[ChargeItem]:
    today = date.today()
    insurance = random.choice(_INSURANCE_PLANS)

    catalogue = {
        "A01": _ADMISSION_CHARGES,
        "A03": _DISCHARGE_CHARGES,
    }.get(trigger_event, _MANUAL_CHARGES)

    items = []
    for idx, (cpt, desc, rev, dept, price) in enumerate(catalogue, start=1):
        qty   = 1
        total = Decimal(str(price)) * qty
        items.append(ChargeItem(
            line_number=idx,
            charge_id=_charge_id(),
            encounter_id=encounter_id,
            service_date=today,
            transaction_type="CG",
            procedure_code=cpt,
            procedure_description=desc,
            revenue_code=rev,
            department=dept,
            unit_amount=Decimal(str(price)),
            quantity=qty,
            total_amount=total,
            insurance_plan=insurance,
        ))
    return items


# ── Segment builders ──────────────────────────────────────────────────────────

def _msh(msg_ctrl_id: str, ts: str) -> str:
    return (
        f"MSH|^~\\&"
        f"|BillingApp|DemoHospital"
        f"|PayerSystem|PayerFacility"
        f"|{ts}"
        f"||DFT^P03"
        f"|{msg_ctrl_id}"
        f"|P|2.3"
    )


def _evn(ts: str) -> str:
    return f"EVN|P03|{ts}"


def _pid(patient_id: str) -> str:
    last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones"]
    first_names = ["James", "Maria", "David", "Sarah", "Michael"]
    last, first = random.choice(last_names), random.choice(first_names)
    dob = f"{random.randint(1950,2000):04d}{random.randint(1,12):02d}{random.randint(1,28):02d}"
    gender = random.choice(["M", "F"])
    return (
        f"PID|1"
        f"||{patient_id}^^^DemoHospital^MR"
        f"||{last}^{first}"
        f"||{dob}|{gender}"
        f"|||{random.randint(100,9999)} Demo St^^Springfield^IL^{random.randint(10000,99999)}"
    )


def _pv1(encounter_id: str) -> str:
    locations = ["ED^001^A", "ICU^204^B", "MED^310^C", "SURG^412^D"]
    doctors   = ["1234^Adams^John", "5678^Brown^Lisa", "9012^Carter^Michael"]
    return (
        f"PV1|1|I"
        f"|{random.choice(locations)}"
        f"|||{random.choice(doctors)}"
        f"|||||1"
        f"|||||||||||||||||||||||||||"
        f"|{encounter_id}"
    )


def _ft1(item: ChargeItem) -> str:
    svc_date = item.service_date.strftime("%Y%m%d")
    return (
        f"FT1"
        f"|{item.line_number}"                    # FT1-1  Set ID
        f"|{item.charge_id}"                      # FT1-2  Transaction ID
        f"|{item.encounter_id}"                   # FT1-3  Batch/Encounter
        f"|{svc_date}"                            # FT1-4  Service Date
        f"|{svc_date}"                            # FT1-5  Posting Date
        f"|{item.transaction_type}"               # FT1-6  Type (CG/CR/PY)
        f"|{item.total_amount}"                   # FT1-7  Amount
        f"|{item.quantity}"                       # FT1-8  Quantity
        f"|{item.unit_amount}"                    # FT1-9  Unit Cost
        f"||{item.procedure_description}"         # FT1-11 Description
        f"|||"
        f"|{item.revenue_code}"                   # FT1-15 Revenue Code
        f"|{item.department}"                     # FT1-16 Department
        f"|{item.insurance_plan}"                 # FT1-17 Insurance Plan
        f"||||||||"
        f"|{item.procedure_code}"                 # FT1-25 Procedure Code
    )


# ── Public API ────────────────────────────────────────────────────────────────

def generate_dft(
    patient_id: str,
    trigger_event: str = "MANUAL",
) -> tuple[str, list[ChargeItem], str]:
    """
    Build a complete DFT^P03 HL7 v2.3 message.

    Parameters
    ----------
    patient_id : str
        Patient MRN (from the triggering ADT event or provided directly).
    trigger_event : str
        ADT event that caused this DFT: "A01", "A03", or "MANUAL".

    Returns
    -------
    tuple[str, list[ChargeItem], str]
        (raw_hl7, charge_items, encounter_id)
    """
    ts           = _now_hl7()
    msg_ctrl_id  = _msg_id()
    encounter_id = _encounter_id(patient_id)
    charges      = _build_charges(trigger_event, encounter_id)

    segments = [
        _msh(msg_ctrl_id, ts),
        _evn(ts),
        _pid(patient_id),
        _pv1(encounter_id),
        *[_ft1(c) for c in charges],
    ]

    raw_hl7 = SEG_SEP.join(segments) + SEG_SEP
    return raw_hl7, charges, encounter_id
