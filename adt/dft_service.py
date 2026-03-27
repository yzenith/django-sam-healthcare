"""
dft_service.py
~~~~~~~~~~~~~~
Orchestrates the ADT → DFT → X12 837P revenue cycle chain.

Call create_dft_from_adt() immediately after an ADTMessage is persisted for
A01 or A03 events. The service:

  1. Generates a DFT^P03 HL7 message with realistic FT1 charge lines.
  2. Converts those charge items directly to an X12 837P professional claim.
  3. Persists DFTMessage + DFTChargeItem rows in a single transaction.

The resulting X12 837 is structurally similar to what the existing
MirthHL7View → fhir_to_837_claim() path produces, but is built from actual
DFT charge data (procedure codes, revenue codes, quantities, unit prices)
rather than a placeholder SV1 line — demonstrating the full revenue cycle audit
trail expected in a production RCM integration.
"""

import logging
import random
import string
from decimal import Decimal

from django.db import transaction

from .dft_generator import ChargeItem, generate_dft
from .models import ADTMessage, DFTChargeItem, DFTMessage

logger = logging.getLogger("adt")


# ── X12 837P builder (charge-item–driven) ─────────────────────────────────────

def _build_x12_837p(
    patient_id: str,
    claim_id: str,
    charges: list[ChargeItem],
) -> str:
    """
    Build a simplified X12 837P professional claim from DFT charge items.

    Each ChargeItem → one LX / SV1 service line, which is the canonical
    mapping from FT1 financial data to an institutional/professional claim.

    CLM01 = claim_id (patient MRN in demo)
    CLM02 = total billed (sum of all FT1 amounts)
    LX/SV1 = one line per FT1, using CPT procedure code + unit amount + qty
    """
    total = sum(c.total_amount for c in charges)
    svc_date = charges[0].service_date.strftime("%Y%m%d") if charges else "20260101"
    insurance = charges[0].insurance_plan if charges else "BCBS"

    segs = [
        "ISA*00*          *00*          *ZZ*SENDERID      *ZZ*RECEIVERID    "
        f"*{svc_date[:6]}*1200*^*00501*000000001*0*T*:~",
        f"GS*HC*BILLINGAPP*PAYERSYSTEM*{svc_date}*1200*1*X*005010X222A1~",
        "ST*837*0001*005010X222A1~",
        f"BHT*0019*00*{claim_id}*{svc_date}*1200*CH~",
        # Billing provider
        "NM1*85*2*DEMO HEALTH CLINIC*****XX*1234567890~",
        "N3*456 CLINIC BLVD~",
        "N4*SPRINGFIELD*IL*62701~",
        # Subscriber
        "HL*1**20*1~",
        "HL*2*1*22*0~",
        f"SBR*P*18*******{insurance}~",
        f"NM1*IL*1*PATIENT*{patient_id}****MI*{patient_id}~",
        "N3*123 MAIN ST~",
        "N4*SPRINGFIELD*IL*62701~",
        # Claim header
        f"CLM*{claim_id}*{total}***11:B:1*Y*A*Y*Y~",
        f"DTP*472*D8*{svc_date}~",       # Service date
        "HI*ABK:Z87.891~",               # Placeholder ICD-10 DX
    ]

    # One LX/SV1 per charge line
    for item in charges:
        segs.append(f"LX*{item.line_number}~")
        segs.append(
            f"SV1*HC:{item.procedure_code}*{item.unit_amount}"
            f"*UN*{item.quantity}***{item.line_number}~"
        )
        segs.append(f"DTP*472*D8*{item.service_date.strftime('%Y%m%d')}~")

    seg_count = len(segs) + 2  # +2 for SE + GE + IEA below
    segs += [
        f"SE*{seg_count}*0001~",
        "GE*1*1~",
        "IEA*1*000000001~",
    ]
    return "\n".join(segs)


def _claim_id(patient_id: str) -> str:
    suffix = "".join(random.choices(string.digits, k=6))
    return f"CLM-{patient_id[:8]}-{suffix}"


# ── Public service call ────────────────────────────────────────────────────────

@transaction.atomic
def create_dft_from_adt(adt_msg: ADTMessage) -> DFTMessage | None:
    """
    Generate and persist a DFT^P03 message linked to the given ADTMessage.

    Only fires for A01 (admit) and A03 (discharge); silently returns None for
    A02 / A08 which don't create new charges in this revenue cycle model.

    Parameters
    ----------
    adt_msg : ADTMessage
        The just-created ADT event row.

    Returns
    -------
    DFTMessage | None
        The persisted DFTMessage, or None if no DFT is warranted.
    """
    if adt_msg.event_type not in (ADTMessage.EventType.A01, ADTMessage.EventType.A03):
        return None

    trigger_event = adt_msg.event_type  # "A01" or "A03"
    patient_id    = adt_msg.patient_id

    try:
        raw_hl7, charges, encounter_id = generate_dft(
            patient_id=patient_id,
            trigger_event=trigger_event,
        )
    except Exception:
        logger.exception("DFT generation failed for adt_id=%s", adt_msg.pk)
        DFTMessage.objects.create(
            adt_message=adt_msg,
            patient_id=patient_id,
            trigger_event=trigger_event,
            raw_hl7="",
            status=DFTMessage.Status.FAILED,
        )
        return None

    total_charges = sum(c.total_amount for c in charges)
    claim_id      = _claim_id(patient_id)
    x12_837       = _build_x12_837p(patient_id, claim_id, charges)

    dft = DFTMessage.objects.create(
        adt_message=adt_msg,
        patient_id=patient_id,
        encounter_id=encounter_id,
        trigger_event=trigger_event,
        raw_hl7=raw_hl7,
        status=DFTMessage.Status.GENERATED,
        total_charges=total_charges,
        claim_id=claim_id,
        x12_837=x12_837,
    )

    DFTChargeItem.objects.bulk_create([
        DFTChargeItem(
            dft_message=dft,
            line_number=c.line_number,
            charge_id=c.charge_id,
            encounter_batch=c.encounter_id,
            service_date=c.service_date,
            transaction_type=c.transaction_type,
            procedure_code=c.procedure_code,
            procedure_description=c.procedure_description,
            revenue_code=c.revenue_code,
            department=c.department,
            unit_amount=c.unit_amount,
            quantity=c.quantity,
            total_amount=c.total_amount,
            insurance_plan=c.insurance_plan,
        )
        for c in charges
    ])

    logger.info(
        "DFT^P03 created: id=%s patient=%s claim=%s total=$%s lines=%d",
        dft.pk, patient_id, claim_id, total_charges, len(charges),
    )
    return dft
