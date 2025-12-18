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

    try:
        if input_type == "JSON":
            import json
            obj = json.loads(raw_payload)
            # Keep a small preview only
            preview = {"type": "JSON", "keys": list(obj.keys())[:20]} if isinstance(obj, dict) else {"type": "JSON", "kind": "list", "len": len(obj)}
            steps.append(StepResult("parse", "OK", "JSON parsed", {"preview": preview}))
        elif input_type == "HL7":
            # Minimal HL7 preview: pull MSH fields, message type if possible
            # Not a full HL7 library—this is MVP traceability
            msh_line = next((ln for ln in raw_payload.splitlines() if ln.startswith("MSH|")), "")
            parts = msh_line.split("|")
            msg_type = parts[8] if len(parts) > 8 else ""
            preview = {"type": "HL7", "segment": "MSH", "message_type": msg_type}
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

    log.parsed_preview = preview
    log.error_count = error_count
    log.summary = _build_summary(input_type, preview, log.status, error_count)
    log.duration_ms = int((time.time() - start) * 1000)
    log.save(update_fields=["parsed_preview", "error_count", "summary", "duration_ms", "status"])

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
