import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .models import TraceLog, TraceStep

"""This service is intentionally “architecturally correct” even if parsing is minimal:

single ingestion entrypoint

deterministic trace_id

ordered step timeline

summary + error_count derived from actual steps

duration captured"""


@dataclass
class StepResult:
    step_name: str
    status: str          # OK/WARN/ERROR
    message: str
    details: Dict[str, Any]


def _guess_input_type(raw_payload: str, declared: Optional[str]) -> str:
    if declared in {"HL7", "JSON", "EDI"}:
        return declared
    s = raw_payload.strip()
    if s.startswith("{") or s.startswith("["):
        return "JSON"
    if "MSH|" in raw_payload:
        return "HL7"
    if s.startswith("ISA") or "*00*" in raw_payload:
        return "EDI"
    return "OTHER"


def _parse_preview(input_type: str, raw_payload: str) -> Tuple[Optional[Dict[str, Any]], List[StepResult]]:
    steps: List[StepResult] = []
    preview: Optional[Dict[str, Any]] = None
    warnings = []

    try:
        if input_type == "JSON":
            import json
            obj = json.loads(raw_payload)
            # Keep a small preview only
            preview = {"type": "JSON", "keys": list(obj.keys())[:20]} if isinstance(obj, dict) else {"type": "JSON", "kind": "list", "len": len(obj)}
            steps.append(StepResult("parse", "OK", "JSON parsed", {"preview": preview}))
        elif input_type == "HL7":
            # Example: if your preview already has extracted PID fields
            pid3 = preview.get("patient_id")  # adjust to your actual key
            dob = preview.get("dob")

            if not pid3:
                warnings.append("Missing PID-3 Patient Identifier")

            if dob and len(dob) != 8:  # expects YYYYMMDD
                warnings.append("Invalid PID-7 DOB format (expected YYYYMMDD)")

            msh_line = next((ln for ln in raw_payload.splitlines() if ln.startswith("MSH|")), "")
            parts = msh_line.split("|")

            # HL7 v2 MSH field positions (0-based index in `parts`)
            # parts[0] = "MSH"
            # parts[1] = encoding chars ^~\&
            # parts[2] = MSH-3 Sending Application
            # parts[3] = MSH-4 Sending Facility
            # parts[4] = MSH-5 Receiving Application
            # parts[5] = MSH-6 Receiving Facility
            # parts[6] = MSH-7 Date/Time of Message
            # parts[8] = MSH-9 Message Type (e.g., ADT^A01)
            # parts[9] = MSH-10 Message Control ID

            msg_type = parts[8] if len(parts) > 8 else ""
            sending_app = parts[2] if len(parts) > 2 else ""
            sending_facility = parts[3] if len(parts) > 3 else ""
            receiving_app = parts[4] if len(parts) > 4 else ""
            receiving_facility = parts[5] if len(parts) > 5 else ""
            message_control_id = parts[9] if len(parts) > 9 else ""

            preview = {
                "type": "HL7",
                "segment": "MSH",
                "message_type": msg_type,
                "sending_app": sending_app,
                "sending_facility": sending_facility,
                "receiving_app": receiving_app,
                "receiving_facility": receiving_facility,
                "message_control_id": message_control_id,
            }
            # persist warnings in preview (or meta)
            preview["warnings"] = warnings
            pid_line = next((ln for ln in raw_payload.splitlines() if ln.startswith("PID|")), "")
            pid_parts = pid_line.split("|") if pid_line else []

            patient_id = pid_parts[3] if len(pid_parts) > 3 else ""   # PID-3
            dob = pid_parts[7] if len(pid_parts) > 7 else ""          # PID-7

            warnings = []
            if not patient_id.strip():
                warnings.append("Missing PID-3 Patient Identifier")

            if dob and (len(dob) != 8 or not dob.isdigit()):
                warnings.append("Invalid PID-7 DOB format (expected YYYYMMDD)")

            preview["patient_id"] = patient_id
            preview["dob"] = dob
            preview["warnings"] = warnings


            steps.append(StepResult("parse", "OK", "HL7 MSH preview extracted", {"preview": preview}))
        elif input_type == "EDI":
            # Minimal EDI preview: pull ISA/GS presence
            preview = {"type": "EDI", "has_ISA": raw_payload.strip().startswith("ISA"), "len": len(raw_payload)}
            steps.append(StepResult("parse", "OK", "EDI envelope preview extracted", {"preview": preview}))
        else:
            preview = {"type": "OTHER", "len": len(raw_payload)}
            steps.append(StepResult("parse", "WARN", "Unknown input type; stored as raw", {"preview": preview}))
    except Exception as e:
        steps.append(StepResult("parse", "ERROR", "Parsing failed", {"error": str(e)}))
        return {"type": input_type, "message_type": "", "warnings": ["Preview parse failed"]}, steps

    return preview, steps


def _validate(preview: Optional[Dict[str, Any]], input_type: str, raw_payload: str) -> List[StepResult]:
    steps: List[StepResult] = []
    errors: List[str] = []

    if input_type == "HL7":
        if "MSH|" not in raw_payload:
            errors.append("Missing MSH segment")
    if input_type == "JSON":
        if preview is None:
            errors.append("JSON preview missing (parse likely failed)")
    if input_type == "EDI":
        if not raw_payload.strip().startswith("ISA"):
            errors.append("Missing ISA segment")

    if errors:
        steps.append(StepResult("validate", "ERROR", "Validation errors found", {"errors": errors}))
    else:
        steps.append(StepResult("validate", "OK", "Validation passed", {}))

    return steps


def ingest_payload(*, raw_payload: str, declared_input_type: Optional[str] = None, output_type: str = "FHIR_JSON", meta: Optional[Dict[str, Any]] = None) -> TraceLog:
    start = time.time()
    trace_id = uuid.uuid4().hex

    input_type = _guess_input_type(raw_payload, declared_input_type)

    log = TraceLog.objects.create(
        trace_id=trace_id,
        input_type=input_type,
        output_type=output_type,
        raw_payload=raw_payload,
        meta=meta or {},
        status=TraceLog.Status.RECEIVED,
        summary="Received payload",
        error_count=0,
    )

    sequence = 1
    all_steps: List[StepResult] = []

    preview, parse_steps = _parse_preview(input_type, raw_payload)
    # Assuming you already create steps from parse_steps
    # existing parse_steps already use a sequence; get next sequence number
    # next_seq = (log.steps.aggregate(models.Max("sequence")).get("sequence__max") or 0) + 1

    for w in preview.get("warnings", []):
        TraceStep.objects.create(
            trace_log=log,
            sequence=next_seq,
            step_name="validate",  # or "parse" depending on where you detect it
            status=TraceStep.StepStatus.WARN,
            message=w[:255],
            details={"kind": "validation_warning"},
        )
        next_seq += 1

    all_steps.extend(parse_steps)

    validate_steps = _validate(preview, input_type, raw_payload)
    all_steps.extend(validate_steps)

    # Transform step (MVP): we are not doing real HL7→FHIR here; we log intended transformation path
    if any(s.status == "ERROR" for s in all_steps):
        all_steps.append(StepResult("transform", "WARN", "Transform skipped due to prior errors", {"target": output_type}))
        log.status = TraceLog.Status.FAILED
    else:
        all_steps.append(StepResult("transform", "OK", "Transform planned (MVP)", {"path": f"{input_type} -> {output_type}"}))
        log.status = TraceLog.Status.PROCESSED

    # Persist steps
    error_count = 0
    for s in all_steps:
        if s.status == "ERROR":
            error_count += 1
        TraceStep.objects.create(
            trace_log=log,
            sequence=sequence,
            step_name=s.step_name,
            status=s.status,
            message=s.message,
            details=s.details,
        )
        sequence += 1

    
    # Normalize meta so UI can filter consistently
    meta_dict = log.meta or {}
    # If caller didn't provide a real source, derive from HL7 header
    raw_source = (meta_dict.get("source_system") or meta_dict.get("source") or "").strip()

 
    if input_type == "HL7" and isinstance(preview, dict):
        sending_app = (preview.get("sending_app") or "").strip()
        sending_fac = (preview.get("sending_facility") or "").strip()


    derived = None
    if sending_app or sending_fac:
        derived = f"{sending_app or 'UNKNOWN_APP'}:{sending_fac or 'UNKNOWN_FAC'}"

    # Only override if meta is missing or looks like a UI placeholder
    if (not raw_source) or (raw_source.lower() in {"trace_ui", "ui", "web"}):
        if derived:
            meta_dict["source_system"] = derived
    

    # Source system normalization (prefer explicit source_system)
    if "source_system" not in meta_dict:
        meta_dict["source_system"] = meta_dict.get("source") or "unknown"

    # Message type normalization (from HL7 preview)
    if preview and input_type == "HL7":
        mt = preview.get("message_type")
        if mt and "message_type" not in meta_dict:
            meta_dict["message_type"] = mt

    log.meta = meta_dict
    log.save(update_fields=["meta", ...])


    log.parsed_preview = preview
    log.error_count = error_count
    log.summary = _build_summary(input_type, preview, log.status, error_count)
    log.duration_ms = int((time.time() - start) * 1000)
    log.save(update_fields=["parsed_preview", "error_count", "summary", "duration_ms", "status","meta"])

    return log


def _build_summary(input_type: str, preview: Optional[Dict[str, Any]], status: str, error_count: int) -> str:
    base = f"{input_type} {status}"
    if preview and input_type == "HL7":
        mt = preview.get("message_type", "")
        if mt:
            base += f" ({mt})"
    if error_count:
        base += f" - {error_count} error(s)"
    return base
