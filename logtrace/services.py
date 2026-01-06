import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .models import TraceLog, TraceStep

"""
This service is intentionally “architecturally correct” even if parsing is minimal:

- single ingestion entrypoint
- deterministic trace_id
- ordered step timeline
- summary + error_count derived from actual steps
- duration captured

Focus: Integration Analyst demo value (traceability, validation, operational flags).
"""


@dataclass
class StepResult:
    step_name: str
    status: str          # OK/WARN/ERROR (matches TraceStep.StepStatus)
    message: str
    details: Dict[str, Any]


def _guess_input_type(raw_payload: str, declared: Optional[str]) -> str:
    if declared in {"HL7", "JSON", "EDI"}:
        return declared
    s = (raw_payload or "").strip()
    if s.startswith("{") or s.startswith("["):
        return "JSON"
    if "MSH|" in (raw_payload or ""):
        return "HL7"
    if s.startswith("ISA") or "*00*" in s:
        return "EDI"
    return "OTHER"


def _parse_preview(input_type: str, raw_payload: str) -> Tuple[Dict[str, Any], List[StepResult]]:
    """
    Returns: (preview_dict, parse_steps)
    preview is ALWAYS a dict (never None) so callers can safely .get().
    """
    steps: List[StepResult] = []
    preview: Dict[str, Any] = {"type": input_type}
    raw_payload = raw_payload or ""

    try:
        if input_type == "JSON":
            import json
            obj = json.loads(raw_payload)
            if isinstance(obj, dict):
                preview = {"type": "JSON", "keys": list(obj.keys())[:20]}
            else:
                preview = {"type": "JSON", "kind": "list", "len": len(obj)}
            steps.append(StepResult("parse", "OK", "JSON parsed", {"preview": preview}))
            return preview, steps

        if input_type == "HL7":
            # --- MSH extraction ---
            msh_line = next((ln for ln in raw_payload.splitlines() if ln.startswith("MSH|")), "")
            msh_parts = msh_line.split("|") if msh_line else []

            # HL7 v2 MSH positions (0-based index in split list):
            # msh_parts[2] = MSH-3 Sending Application
            # msh_parts[3] = MSH-4 Sending Facility
            # msh_parts[4] = MSH-5 Receiving Application
            # msh_parts[5] = MSH-6 Receiving Facility
            # msh_parts[8] = MSH-9 Message Type (e.g., ADT^A01)
            # msh_parts[9] = MSH-10 Message Control ID
            msg_type = msh_parts[8] if len(msh_parts) > 8 else ""
            sending_app = msh_parts[2] if len(msh_parts) > 2 else ""
            sending_facility = msh_parts[3] if len(msh_parts) > 3 else ""
            receiving_app = msh_parts[4] if len(msh_parts) > 4 else ""
            receiving_facility = msh_parts[5] if len(msh_parts) > 5 else ""
            message_control_id = msh_parts[9] if len(msh_parts) > 9 else ""

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

            # --- Minimal PID extraction for analyst-style warnings ---
            pid_line = next((ln for ln in raw_payload.splitlines() if ln.startswith("PID|")), "")
            pid_parts = pid_line.split("|") if pid_line else []
            patient_id = pid_parts[3] if len(pid_parts) > 3 else ""   # PID-3
            dob = pid_parts[7] if len(pid_parts) > 7 else ""          # PID-7

            preview["patient_id"] = patient_id
            preview["dob"] = dob

            warnings: List[str] = []
            if not patient_id.strip():
                warnings.append("Missing PID-3 Patient Identifier")

            if dob and (len(dob) != 8 or not dob.isdigit()):
                warnings.append("Invalid PID-7 DOB format (expected YYYYMMDD)")

            preview["warnings"] = warnings

            steps.append(StepResult("parse", "OK", "HL7 preview extracted (MSH/PID)", {"preview": preview}))
            return preview, steps

        if input_type == "EDI":
            preview = {"type": "EDI", "has_ISA": raw_payload.strip().startswith("ISA"), "len": len(raw_payload)}
            steps.append(StepResult("parse", "OK", "EDI envelope preview extracted", {"preview": preview}))
            return preview, steps

        # OTHER
        preview = {"type": "OTHER", "len": len(raw_payload)}
        steps.append(StepResult("parse", "WARN", "Unknown input type; stored as raw", {"preview": preview}))
        return preview, steps

    except Exception as e:
        # Never raise here; keep traceability and show WARN/ERROR step
        preview = {"type": input_type, "message_type": "", "warnings": ["Preview parse failed"]}
        steps.append(StepResult("parse", "ERROR", "Parsing failed", {"error": str(e)}))
        return preview, steps


def _validate(preview: Dict[str, Any], input_type: str, raw_payload: str) -> List[StepResult]:
    steps: List[StepResult] = []
    errors: List[str] = []
    raw_payload = raw_payload or ""

    if input_type == "HL7":
        if "MSH|" not in raw_payload:
            errors.append("Missing MSH segment")

    if input_type == "JSON":
        if not preview or preview.get("type") != "JSON":
            errors.append("JSON preview missing or invalid (parse likely failed)")

    if input_type == "EDI":
        if not raw_payload.strip().startswith("ISA"):
            errors.append("Missing ISA segment")

    if errors:
        steps.append(StepResult("validate", "ERROR", "Validation errors found", {"errors": errors}))
    else:
        steps.append(StepResult("validate", "OK", "Validation passed", {}))

    return steps


def _build_summary(input_type: str, preview: Dict[str, Any], status: str, error_count: int) -> str:
    base = f"{input_type} {status}"
    if input_type == "HL7":
        mt = (preview or {}).get("message_type", "")
        if mt:
            base += f" ({mt})"
    if error_count:
        base += f" - {error_count} error(s)"
    return base


def ingest_payload(
    *,
    raw_payload: str,
    declared_input_type: Optional[str] = None,
    output_type: str = "FHIR_JSON",
    meta: Optional[Dict[str, Any]] = None,
) -> TraceLog:
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

    all_steps: List[StepResult] = []

    # 1) Parse preview
    preview, parse_steps = _parse_preview(input_type, raw_payload)
    all_steps.extend(parse_steps)

    # 2) Convert preview warnings to trace steps (analyst-visible)
    if input_type == "HL7":
        for w in (preview.get("warnings") or []):
            all_steps.append(
                StepResult(
                    step_name="validate",
                    status=TraceStep.StepStatus.WARN,
                    message=str(w),
                    details={"kind": "validation_warning"},
                )
            )

    # 3) Validate
    validate_steps = _validate(preview, input_type, raw_payload)
    all_steps.extend(validate_steps)

    # 4) Transform step (MVP): log intended transformation path
    if any(s.status == TraceStep.StepStatus.ERROR for s in all_steps):
        all_steps.append(
            StepResult(
                "transform",
                TraceStep.StepStatus.WARN,
                "Transform skipped due to prior errors",
                {"target": output_type},
            )
        )
        log.status = TraceLog.Status.FAILED
    else:
        all_steps.append(
            StepResult(
                "transform",
                TraceStep.StepStatus.OK,
                "Transform planned (MVP)",
                {"path": f"{input_type} -> {output_type}"},
            )
        )
        log.status = TraceLog.Status.PROCESSED

    # 5) Persist steps (single pass, correct sequencing)
    error_count = 0
    sequence = 1
    for s in all_steps:
        if s.status == TraceStep.StepStatus.ERROR:
            error_count += 1

        TraceStep.objects.create(
            trace_log=log,
            sequence=sequence,
            step_name=s.step_name,
            status=s.status,
            message=(s.message or "")[:255],
            details=s.details or {},
        )
        sequence += 1

    # 6) Normalize meta for analyst UI (source_system, message_type)
    meta_dict = log.meta or {}
    if not isinstance(meta_dict, dict):
        meta_dict = {}

    raw_source = (meta_dict.get("source_system") or meta_dict.get("source") or "").strip()

    sending_app = (preview.get("sending_app") or "").strip() if input_type == "HL7" else ""
    sending_fac = (preview.get("sending_facility") or "").strip() if input_type == "HL7" else ""
    derived_source = f"{sending_app or 'UNKNOWN_APP'}:{sending_fac or 'UNKNOWN_FAC'}" if (sending_app or sending_fac) else ""

    # Prefer derived upstream system over UI placeholder
    if (not raw_source) or (raw_source.lower() in {"trace_ui", "ui", "web"}):
        meta_dict["source_system"] = derived_source or "unknown"
    else:
        meta_dict["source_system"] = raw_source

    # Normalize message_type into meta for filtering
    if input_type == "HL7":
        mt = preview.get("message_type")
        if mt:
            meta_dict.setdefault("message_type", mt)

    log.meta = meta_dict

    # 7) Final log fields
    log.parsed_preview = preview
    log.error_count = error_count
    log.summary = _build_summary(input_type, preview, log.status, error_count)
    log.duration_ms = int((time.time() - start) * 1000)
    log.save(update_fields=["parsed_preview", "error_count", "summary", "duration_ms", "status", "meta"])

    return log
