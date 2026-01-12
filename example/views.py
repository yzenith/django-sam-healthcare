import json
import os
import uuid
import csv
import io
from django.http import HttpResponseForbidden, HttpResponse

import jwt
from datetime import datetime
from django.utils.timezone import now
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.renderers import JSONRenderer
from django.shortcuts import get_object_or_404, render, redirect
from .hl7_utils import (
    hl7_to_all,
    extract_hl7_summary,
    validate_hl7_message,
    build_message_profile,
    build_trigger_event,
    extract_source_context_from_msh,
    hl7_oru_to_fhir,
)

from .models import HL7MessageLog, PatientRecord, PatientImportRun

# JWT settings – use env vars in real deployment
MIRTH_JWT_SECRET = os.environ.get("MIRTH_JWT_SECRET", "MIRTH_DEMO_SECRET_KEY")
MIRTH_JWT_ALG = "HS256"
MIRTH_JWT_AUD = "mirth-connector"
MIRTH_JWT_ISS = "django-sam-healthcare"

# helpers for patient import
def _norm_str(v):
    return (v or "").strip()

# parse date of birth from various formats
def _parse_dob(v):
    v = _norm_str(v)
    if not v:
        return None
    # Accept YYYY-MM-DD or YYYYMMDD
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            pass
    return None

# normalize US state to 2-letter code
def _norm_state(v):
    v = _norm_str(v).upper()
    return v[:2]

# ⬇⬇⬇ add patient import rejects CSV view
def patient_import_rejects_csv(request, pk: int):
    run = get_object_or_404(PatientImportRun, pk=pk)

    # reject_samples is a list of {"rownum": idx, "reason": "...", "row": {original csv row dict}}
    samples = run.reject_samples or []

    # Collect original CSV fieldnames seen in reject samples
    fieldnames = set()
    for item in samples:
        row = item.get("row") or {}
        fieldnames.update(row.keys())

    # Stable ordering: standard columns first, then the rest
    standard = ["mrn", "first_name", "last_name", "dob", "gender", "address1", "city", "state", "zip_code", "zip"]
    ordered_fields = [f for f in standard if f in fieldnames] + sorted([f for f in fieldnames if f not in standard])

    header = ["rownum", "reason"] + ordered_fields

    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="patient_import_{run.id}_rejects.csv"'

    writer = csv.DictWriter(resp, fieldnames=header, extrasaction="ignore")
    writer.writeheader()

    for item in samples:
        out = {"rownum": item.get("rownum", ""), "reason": item.get("reason", "")}
        row = item.get("row") or {}
        for k in ordered_fields:
            out[k] = row.get(k, "")
        writer.writerow(out)

    return resp


# ⬇⬇⬇ add patient import views
def patient_import_page(request):
    """
    GET: show upload + recent runs
    POST: process CSV upload (multipart/form-data)
    """
    if request.method == "GET":
        runs = PatientImportRun.objects.order_by("-created_at")[:20]
        return render(request, "patient_import.html", {"runs": runs})

    # POST
    upload = request.FILES.get("csv_file")
    if not upload:
        runs = PatientImportRun.objects.order_by("-created_at")[:20]
        return render(request, "patient_import.html", {
            "runs": runs,
            "error": "Please choose a CSV file.",
        })

    run = PatientImportRun.objects.create(filename=upload.name, status=PatientImportRun.Status.RECEIVED)

    try:
        raw = upload.read().decode("utf-8", errors="ignore")
        f = io.StringIO(raw)
        reader = csv.DictReader(f)

        # Required columns (minimal)
        required = {"mrn", "first_name", "last_name", "dob"}
        headers = set([h.strip() for h in (reader.fieldnames or []) if h])
        missing = required - headers
        if missing:
            run.status = PatientImportRun.Status.FAILED
            run.error_message = f"Missing required columns: {sorted(list(missing))}"
            run.save()
            return redirect("patient-import-detail", pk=run.pk)

        seen = set()
        rows = []
        reject_samples = []
        duplicates = 0
        total = 0

        for idx, row in enumerate(reader, start=2):  # header is line 1
            total += 1

            mrn = _norm_str(row.get("mrn"))
            if not mrn:
                if len(reject_samples) < 50:
                    reject_samples.append({"rownum": idx, "reason": "Missing mrn", "row": row})
                continue

            if mrn in seen:
                duplicates += 1
                continue
            seen.add(mrn)

            dob = _parse_dob(row.get("dob"))
            if row.get("dob") and dob is None:
                if len(reject_samples) < 50:
                    reject_samples.append({"rownum": idx, "reason": "Invalid dob format", "row": row})
                continue

            rows.append({
                "mrn": mrn,
                "first_name": _norm_str(row.get("first_name")),
                "last_name": _norm_str(row.get("last_name")),
                "dob": dob,
                "gender": _norm_str(row.get("gender")).upper(),
                "address1": _norm_str(row.get("address1")),
                "city": _norm_str(row.get("city")),
                "state": _norm_state(row.get("state")),
                "zip_code": _norm_str(row.get("zip_code") or row.get("zip")),
            })

        # Upsert in bulk
        mrns = [r["mrn"] for r in rows]
        existing = PatientRecord.objects.filter(mrn__in=mrns)
        existing_by_mrn = {p.mrn: p for p in existing}

        to_create = []
        to_update = []

        for r in rows:
            obj = existing_by_mrn.get(r["mrn"])
            if not obj:
                to_create.append(PatientRecord(**r))
            else:
                # update fields
                obj.first_name = r["first_name"]
                obj.last_name = r["last_name"]
                obj.dob = r["dob"]
                obj.gender = r["gender"]
                obj.address1 = r["address1"]
                obj.city = r["city"]
                obj.state = r["state"]
                obj.zip_code = r["zip_code"]
                to_update.append(obj)

        with transaction.atomic():
            if to_create:
                PatientRecord.objects.bulk_create(to_create, batch_size=500)
            if to_update:
                PatientRecord.objects.bulk_update(
                    to_update,
                    ["first_name", "last_name", "dob", "gender", "address1", "city", "state", "zip_code"],
                    batch_size=500
                )

        inserted = len(to_create)
        updated = len(to_update)
        rejected = (total - duplicates) - (inserted + updated)

        run.total_rows = total
        run.inserted = inserted
        run.updated = updated
        run.duplicates_in_file = duplicates
        run.rejected = rejected
        run.reject_samples = reject_samples
        run.status = PatientImportRun.Status.COMPLETED
        run.reconciliation = {
            "source_rows": total,
            "deduped_rows": total - duplicates,
            "inserted": inserted,
            "updated": updated,
            "rejected": rejected,
            "duplicates_in_file": duplicates,
            "reject_sample_count": len(reject_samples),
            "timestamp": now().isoformat(),
        }
        run.save()

        return redirect("patient-import-detail", pk=run.pk)

    except Exception as e:
        run.status = PatientImportRun.Status.FAILED
        run.error_message = str(e)
        run.save()
        return redirect("patient-import-detail", pk=run.pk)

# ⬇⬇⬇ add patient import detail view
def patient_import_detail(request, pk: int):
    run = get_object_or_404(PatientImportRun, pk=pk)
    return render(request, "patient_import_detail.html", {"run": run})


# ⬇⬇⬇ add Mirth JWT validation
def validate_mirth_jwt(request):
    """
    Extract and validate a Bearer JWT from the Authorization header.

    Expected:
      Authorization: Bearer <token>
    """

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, "Missing or invalid Authorization header"

    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        return None, "Empty JWT token"

    try:
        claims = jwt.decode(
            token,
            MIRTH_JWT_SECRET,
            algorithms=[MIRTH_JWT_ALG],
            audience=MIRTH_JWT_AUD,
            options={"require": ["exp", "iss", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        return None, "JWT has expired"
    except jwt.InvalidTokenError as e:
        return None, f"Invalid JWT: {e}"

    # Optional: enforce issuer
    if claims.get("iss") != MIRTH_JWT_ISS:
        return None, "Invalid JWT issuer"

    return claims, None


def home(request):
    total = HL7MessageLog.objects.count()
    latest_logs = HL7MessageLog.objects.order_by("-created_at")[:5]
    return render(request, "home.html", {
        "total": total,
        "latest_logs": latest_logs,
    })

def hl7_playground(request):
    return render(request, "hl7_playground.html")

def mirth_messages(request):
    # logs = HL7MessageLog.objects.order_by("-created_at")[:20]
    qs = HL7MessageLog.objects.order_by("-created_at")

    status_q = request.GET.get("status")
    if status_q:
        qs = qs.filter(processing_status=status_q)

    type_q = request.GET.get("type")
    if type_q:
        qs = qs.filter(message_type__icontains=type_q)

    logs = qs[:50]
    return render(request, "mirth_messages.html", {"logs": logs})
    

def mirth_message_detail(request, pk):
    log = get_object_or_404(HL7MessageLog, pk=pk)

    # Re-run transform on the raw HL7 so we don't need to store JSON in DB
    transform_result = hl7_to_all(log.raw_hl7)
    patient = transform_result.get("patient")
    encounter = transform_result.get("encounter")
    x12_837 = transform_result.get("x12_837")
    x12_835 = transform_result.get("x12_835")
    claim_reconciliation = transform_result.get("claim_reconciliation")



    context = {
        "log": log,
        "patient": patient,
        "encounter": encounter,
        "x12_837": x12_837,
        "x12_835": x12_835,
        "claim_reconciliation_json": json.dumps(claim_reconciliation, indent=2) if claim_reconciliation else None,

    }

    if log.message_type == "ORU^R01":
        result = hl7_oru_to_fhir(log.raw_hl7)
        report = result["report"]
        observations = result["observations"]

        context.update({
            "report_json": json.dumps(report, indent=2),
            "observations_json": json.dumps(observations, indent=2),
        })

    
    return render(request, "mirth_message_detail.html", context)


# ⬇⬇⬇ add this function-based view
def index(request):
    # if your file is templates/index.html and TEMPLATES.DIRS 已经配置好，
    # 这个名字就是 "index.html"
    return render(request, "index.html")

class HL7TransformView(APIView):
    renderer_classes = [JSONRenderer]

    def post(self, request, *args, **kwargs):
        # JSON requests: use DRF parser (request.data) and DO NOT touch request.body
        if request.content_type and "application/json" in request.content_type:
            data = request.data or {}
            hl7_message = (data.get("hl7_message") or data.get("hl7") or "").strip()
        else:
            # Non-JSON: use raw body and DO NOT touch request.data
            hl7_message = request.body.decode("utf-8", errors="ignore").strip()

        if not hl7_message:
            return Response({"error": "Missing hl7_message"}, status=400)

        # optional quick validation
        if not hl7_message.startswith("MSH"):
            return Response({"error": "Invalid HL7 message"}, status=400)

        result = hl7_to_all(hl7_message)
        return Response(result, status=status.HTTP_200_OK)


    
class MirthHL7View(APIView):
    def post(self, request, *args, **kwargs):
        trace_id = uuid.uuid4().hex

        claims, jwt_err = validate_mirth_jwt(request)
        if jwt_err:
            HL7MessageLog.objects.create(
                trace_id=trace_id,
                source_system="MIRTH",
                message_type="",
                raw_hl7="",
                processing_status=HL7MessageLog.ProcessingStatus.FAILED,
                error_category=HL7MessageLog.ErrorCategory.AUTH,
                error_message=jwt_err[:1000],
                steps=[{"sequence": 1, "step": "AUTH", "status": "ERROR", "message": jwt_err[:255]}],
            )
            return HttpResponseForbidden(jwt_err)

        # 1) 读取 HL7（你可以按你的 payload key 改）

        ### Old version:
        # hl7_message = request.data.get("hl7_message") or request.data.get("hl7") or ""
        # if not isinstance(hl7_message, str) or not hl7_message.strip():
        #     return Response(
        #         {"status": "error", "trace_id": trace_id, "error": "Missing hl7_message"},
        #         status=status.HTTP_400_BAD_REQUEST,
        #     )


        body = request.body.decode("utf-8", errors="ignore").strip()

        hl7_message = ""
        if request.content_type and "application/json" in request.content_type:
            try:
                data = json.loads(body) if body else {}
                hl7_message = data.get("hl7_message") or data.get("hl7") or ""
            except ValueError:
                hl7_message = body
        else:
            hl7_message = body

        if not hl7_message.strip():
            ...

        # 2) 初始化 steps（你截图里用到了 steps，但没定义）
        steps = []
        steps.append({"sequence": 1, "step": "RECEIVED", "status": "OK"})

        # 3) normalize 换行符（Mirth 常见 \r）
        normalized = hl7_message.replace("\r\n", "\n").replace("\r", "\n")

        # 4) validate + summary
        errors, warn_list = validate_hl7_message(normalized)
        summary = extract_hl7_summary(normalized) or {}
        message_profile = build_message_profile(summary.get("message_type") or "")
        trigger_event = build_trigger_event(summary.get("message_type") or "")

        incoming_source_context = {}
        if request.content_type and "application/json" in request.content_type:
            incoming_source_context = (data.get("source_context") or {}) if isinstance(data, dict) else {}

        if not isinstance(incoming_source_context, dict):
            incoming_source_context = {}

        msh_ctx = extract_source_context_from_msh(normalized)

        # 你想要的“EMR / vendor / facility_type”等可以从 payload 进来覆盖
        # payload 例子：
        # {
        #   "hl7_message": "...",
        #   "source_context": {"system_type":"EMR","vendor":"Epic","facility_type":"Acute Care Hospital"}
        # }
        source_context = {**msh_ctx, **incoming_source_context}

        if errors:
            steps.append(
                {
                    "sequence": 2,
                    "step": "VALIDATION",
                    "status": "ERROR",
                    "message": "; ".join(errors)[:500],
                }
            )

            HL7MessageLog.objects.create(
                trace_id=trace_id,
                source_system="MIRTH",
                source_context=source_context,
                message_type=summary.get("message_type") or "",
                message_profile=message_profile,
                trigger_event=trigger_event,
                raw_hl7=normalized,
                processing_status=HL7MessageLog.ProcessingStatus.FAILED,
                error_category=HL7MessageLog.ErrorCategory.VALIDATION,
                error_message="; ".join(errors)[:1000],
                steps=steps,
            )

            return Response(
                {
                    "status": "failed",
                    "trace_id": trace_id,
                    "error_category": "VALIDATION",
                    "errors": errors,
                    "warnings": warn_list,
                    "summary": summary,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        steps.append({"sequence": 2, "step": "VALIDATION", "status": "OK"})
        result = hl7_to_all(normalized)
        x12_837 = result.get("x12_837") or ""
        patient_id = (summary.get("patient_id") or "")[:64]
        encounter_present = bool(summary.get("encounter_present"))
        patient_class = (summary.get("patient_class") or "")[:8]
        event_time = summary.get("event_time")  # 如果你 summary 里是 datetime，直接用
        x12_length = len(x12_837) if isinstance(x12_837, str) else 0
        has_x12 = bool(x12_837)
        steps.append({"sequence": 3, "step": "TRANSFORM", "status": "OK"})

        # validate 通过后，加入一个轻量判断（不挡请求，只写 steps/warnings）：
        error_category = HL7MessageLog.ErrorCategory.NONE
        error_message = ""
        if not source_context.get("sending_application") or not source_context.get("sending_facility"):
            warn_list.append("Missing MSH-3/4 (sending application/facility); common facility variance.")
            error_category = HL7MessageLog.ErrorCategory.FACILITY_VARIANCE
            error_message = "Facility variance: missing MSH-3/4; routing/config may differ."

        

        HL7MessageLog.objects.create(
            trace_id=trace_id,
            source_system="MIRTH",
            source_context=source_context,
            message_type=summary.get("message_type") or "",
            message_profile=message_profile,
            trigger_event=trigger_event,
            raw_hl7=normalized,
            processing_status=HL7MessageLog.ProcessingStatus.TRANSFORMED,
            # error_category=HL7MessageLog.ErrorCategory.NONE,
            # error_message="",
            steps=steps,
            # has_x12=bool(result.get("x12_837")),
            patient_id=patient_id,
            encounter_present=encounter_present,
            patient_class=patient_class,
            event_time=event_time,
            x12_length=x12_length,
            has_x12=has_x12,
            error_category=error_category,
            error_message=error_message,
        )

        return Response(
            {
                "status": "ok",
                "trace_id": trace_id,
                "summary": summary,
                "warnings": warn_list,
                "fhir": result.get("fhir"),
                "x12_837": result.get("x12_837"),
            },
            status=status.HTTP_200_OK,
        )

