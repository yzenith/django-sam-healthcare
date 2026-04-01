"""
example/seed_demo.py

Shared seeding logic — called by both:
  - python manage.py seed_demo_data
  - POST /seed-demo-data/  (home page button)

Creates realistic demo records across every message type so a recruiter
lands on the site and sees a populated, working pipeline instead of
empty tables.

Timestamps are always generated relative to NOW so the data always
looks current (within the last 72 hours).
"""
import uuid
from datetime import datetime, timezone, timedelta
from example.hl7_utils import (
    hl7_to_all, validate_hl7_message, extract_hl7_summary,
    build_message_profile, build_trigger_event,
    extract_source_context_from_msh, generate_ack,
)


def _ts(hours_ago=0, minutes_ago=0):
    """Return an HL7 timestamp string relative to now."""
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago, minutes=minutes_ago)
    return dt.strftime("%Y%m%d%H%M%S")


def _build_seed_messages():
    """
    Build SEED_MESSAGES list with timestamps relative to now.
    Called fresh on every seed so timestamps stay current.
    """
    return [
        # --- ADT A01: Inpatient admission (normal) ---
        {
            "hl7": (
                f"MSH|^~\\&|EPIC|MEMORIAL_HOSP|MIRTH|FACILITY|{_ts(hours_ago=48)}||ADT^A01|ADT001|P|2.5\r"
                "PID|1||10001^^^MRN||JOHNSON^ALICE||19720315|F|||100 MAIN ST^^DALLAS^TX^75201\r"
                f"PV1|1|I|CARDIAC^101^A||||2001^SMITH^ROBERT|||INT||||ADM|||{_ts(hours_ago=48)}\r"
            ),
        },
        # --- ADT A03: Discharge (triggers 837+835) ---
        {
            "hl7": (
                f"MSH|^~\\&|EPIC|MEMORIAL_HOSP|MIRTH|FACILITY|{_ts(hours_ago=42)}||ADT^A03|ADT002|P|2.5\r"
                "PID|1||10001^^^MRN||JOHNSON^ALICE||19720315|F\r"
                f"PV1|1|I|CARDIAC^101^A||||2001^SMITH^ROBERT|||INT||||||{_ts(hours_ago=48)}\r"
            ),
        },
        # --- ADT A04: ER registration ---
        {
            "hl7": (
                f"MSH|^~\\&|CERNER|RIVERSIDE_MED|MIRTH|FACILITY|{_ts(hours_ago=36)}||ADT^A04|ADT003|P|2.5\r"
                "PID|1||10002^^^MRN||GARCIA^MIGUEL||19850620|M|||456 OAK AVE^^IRVING^TX^75062\r"
                "PV1|1|E|ER^E01^1||||3001^DAVIS^SARAH|||EM\r"
            ),
        },
        # --- ADT A01: Facility variance (missing MSH-3/4) ---
        {
            "hl7": (
                f"MSH|^~\\&|||MIRTH|FACILITY|{_ts(hours_ago=30)}||ADT^A01|ADT004|P|2.5\r"
                "PID|1||10003^^^MRN||CHEN^LI||19900810|F\r"
                "PV1|1|O|CLINIC^201^B\r"
            ),
        },
        # --- ADT A01: Validation failure (missing PID-3) ---
        {
            "hl7": (
                f"MSH|^~\\&|EPIC|MEMORIAL_HOSP|MIRTH|FACILITY|{_ts(hours_ago=24)}||ADT^A01|ADT005|P|2.5\r"
                "PID|1||||DOE^UNKNOWN||19700101|M\r"
                "PV1|1|I|GENERAL^301^C\r"
            ),
        },
        # --- ADT A08: Update patient info ---
        {
            "hl7": (
                f"MSH|^~\\&|EPIC|MEMORIAL_HOSP|MIRTH|FACILITY|{_ts(hours_ago=18)}||ADT^A08|ADT006|P|2.5\r"
                "PID|1||10001^^^MRN||JOHNSON^ALICE||19720315|F|||200 NEW ST^^DALLAS^TX^75202\r"
            ),
        },
        # --- ORU R01: Normal lab result ---
        {
            "hl7": (
                f"MSH|^~\\&|LAB_SYS|MEMORIAL_HOSP|EHR|FACILITY|{_ts(hours_ago=12)}||ORU^R01|ORU001|P|2.5\r"
                "PID|1||10001^^^MRN||JOHNSON^ALICE||19720315|F\r"
                f"OBR|1||LAB001|1558-6^Hemoglobin^LN|||{_ts(hours_ago=12)}\r"
                "OBX|1|NM|1558-6^Hemoglobin^LN||13.5|g/dL|12.0-16.0|N\r"
                "OBX|2|NM|787-2^MCV^LN||88|fL|80-100|N\r"
            ),
        },
        # --- ORU R01: Abnormal lab result ---
        {
            "hl7": (
                f"MSH|^~\\&|LAB_SYS|RIVERSIDE_MED|EHR|FACILITY|{_ts(hours_ago=8)}||ORU^R01|ORU002|P|2.5\r"
                "PID|1||10002^^^MRN||GARCIA^MIGUEL||19850620|M\r"
                f"OBR|1||LAB002|2093-3^Cholesterol^LN|||{_ts(hours_ago=8)}\r"
                "OBX|1|NM|2093-3^Cholesterol^LN||245|mg/dL|<200|H\r"
            ),
        },
        # --- ORM O01: New lab order ---
        {
            "hl7": (
                f"MSH|^~\\&|ORDERENTRY|MEMORIAL_HOSP|LAB|FACILITY|{_ts(hours_ago=6)}||ORM^O01|ORM001|P|2.5\r"
                "PID|1||10003^^^MRN||CHEN^LI||19900810|F\r"
                f"ORC|NW|ORD001|||||||{_ts(hours_ago=6)}\r"
                f"OBR|1|ORD001||55231-5^Basic metabolic panel^LN||R|{_ts(hours_ago=5)}\r"
            ),
        },
        # --- MDM T02: Consultation note ---
        {
            "hl7": (
                f"MSH|^~\\&|EHR_DOC|MEMORIAL_HOSP|CDMS|FACILITY|{_ts(hours_ago=4)}||MDM^T02|MDM001|P|2.5\r"
                "PID|1||10001^^^MRN||JOHNSON^ALICE||19720315|F\r"
                f"EVN|T02|{_ts(hours_ago=4)}\r"
                f"TXA|1|11488-4^Consultation note^LN||{_ts(hours_ago=4)}||||||||DOC001||||||AU\r"
            ),
        },
        # --- SIU S12: New appointment ---
        {
            "hl7": (
                f"MSH|^~\\&|SCHEDULING|MEMORIAL_HOSP|EHR|FACILITY|{_ts(hours_ago=2)}||SIU^S12|SIU001|P|2.5\r"
                "SCH|APT001|FIL001|||||||30||^^^20260120090000||||||||||||||Pending\r"
                "PID|1||10002^^^MRN||GARCIA^MIGUEL||19850620|M\r"
                "AIS|1||40701008^Cardiology consultation^SCT\r"
                "AIP|1||2001^SMITH^ROBERT\r"
            ),
        },
        # --- SIU S15: Appointment cancelled ---
        {
            "hl7": (
                f"MSH|^~\\&|SCHEDULING|MEMORIAL_HOSP|EHR|FACILITY|{_ts(minutes_ago=30)}||SIU^S15|SIU002|P|2.5\r"
                "SCH|APT002|FIL002|||||||60||^^^20260120140000||||||||||||||Cancelled\r"
                "PID|1||10001^^^MRN||JOHNSON^ALICE||19720315|F\r"
                "AIS|1||40701008^Cardiology consultation^SCT\r"
            ),
        },
    ]


def seed_demo_data(clear_existing=False):
    """
    Create realistic demo records for every HL7 message type.
    Returns a summary dict with counts of created records.

    Args:
        clear_existing: If True, delete existing SEED records first.

    This function is idempotent when clear_existing=False:
    it skips if SEED records already exist.
    """
    from example.models import HL7MessageLog, ClaimRecord, WebhookDelivery
    from example.webhook_service import dispatch_webhooks_for_result

    if clear_existing:
        HL7MessageLog.objects.filter(source_system="SEED").delete()

    if HL7MessageLog.objects.filter(source_system="SEED").exists():
        return {"skipped": True, "reason": "Demo data already exists. Use clear=True to reset."}

    created_logs = 0
    created_claims = 0
    created_webhooks = 0

    for item in _build_seed_messages():
        hl7_raw = item["hl7"]

        errors, warnings = validate_hl7_message(hl7_raw)
        summary = extract_hl7_summary(hl7_raw)
        source_context = extract_source_context_from_msh(hl7_raw)
        message_type = summary.get("message_type", "")
        message_profile = build_message_profile(message_type)
        trigger_event = build_trigger_event(message_type)

        if errors:
            processing_status = HL7MessageLog.ProcessingStatus.FAILED
            error_category = HL7MessageLog.ErrorCategory.VALIDATION
            error_message = "; ".join(errors)
            result = {}
        else:
            result = hl7_to_all(hl7_raw)
            processing_status = HL7MessageLog.ProcessingStatus.TRANSFORMED
            error_message = ""
            # Facility variance — missing MSH-3/4
            if not source_context.get("sending_application") or not source_context.get("sending_facility"):
                error_category = HL7MessageLog.ErrorCategory.FACILITY_VARIANCE
            else:
                error_category = HL7MessageLog.ErrorCategory.NONE

        x12_837 = result.get("x12_837") or ""
        has_x12 = bool(x12_837)

        msg_log = HL7MessageLog.objects.create(
            trace_id=uuid.uuid4().hex,
            source_system="SEED",
            source_context=source_context,
            message_type=message_type,
            message_profile=message_profile,
            trigger_event=trigger_event,
            raw_hl7=hl7_raw,
            processing_status=processing_status,
            error_category=error_category,
            error_message=error_message,
            steps=[
                {"sequence": 1, "step": "AUTH", "status": "OK"},
                {"sequence": 2, "step": "VALIDATION", "status": "ERROR" if errors else "OK"},
                {"sequence": 3, "step": "TRANSFORM", "status": "OK" if not errors else "SKIPPED"},
            ],
            patient_id=(summary.get("patient_id") or "")[:64],
            encounter_present=summary.get("encounter_present", False),
            patient_class=(summary.get("patient_class") or "")[:8],
            event_time=summary.get("event_time"),
            x12_length=len(x12_837),
            has_x12=has_x12,
        )
        created_logs += 1

        # Claim record for ADT messages with X12
        recon = result.get("claim_reconciliation")
        if has_x12 and recon:
            status_map = {"paid": ClaimRecord.ClaimStatus.PAID, "denied": ClaimRecord.ClaimStatus.DENIED}
            claim_status = status_map.get(recon.get("status"), ClaimRecord.ClaimStatus.SUBMITTED)
            ClaimRecord.objects.create(
                message_log=msg_log,
                trace_id=msg_log.trace_id,
                claim_id=recon.get("claim_id", ""),
                patient_id=msg_log.patient_id,
                status=claim_status,
                billed_amount=recon.get("billed_total", 0),
                paid_amount=recon.get("paid_amount", 0),
                patient_responsibility=recon.get("patient_responsibility", 0),
                balance_due=recon.get("balance_due_to_provider", 0),
                x12_837=x12_837,
                x12_835=result.get("x12_835") or "",
            )
            created_claims += 1

        # Webhook deliveries for successful transforms
        if not errors and result:
            deliveries = dispatch_webhooks_for_result(result, trace_id=msg_log.trace_id)
            created_webhooks += len(deliveries)

    return {
        "skipped": False,
        "messages": created_logs,
        "claims": created_claims,
        "webhooks": created_webhooks,
    }
