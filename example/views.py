from django.db.models import Q
from logtrace.models import TraceLog

import json
import os
import uuid
import csv
import io
import random
from django.db import connection
from django.http import HttpResponseForbidden, HttpResponse, JsonResponse

import jwt
from datetime import datetime
from django.utils.timezone import now
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.renderers import JSONRenderer
from drf_spectacular.utils import extend_schema, OpenApiExample, inline_serializer
from rest_framework import serializers as drf_serializers
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from .hl7_utils import (
    hl7_to_all,
    extract_hl7_summary,
    validate_hl7_message,
    build_message_profile,
    build_trigger_event,
    extract_source_context_from_msh,
    hl7_oru_to_fhir,
    generate_ack,
)

from .models import HL7MessageLog, PatientRecord, PatientImportRun, ClaimRecord, WebhookDelivery
from .webhook_service import dispatch_webhooks_for_result

# JWT settings – use env vars in real deployment
from django.conf import settings as _django_settings
from django.core.exceptions import ImproperlyConfigured

_MIRTH_JWT_SECRET_ENV = os.environ.get("MIRTH_JWT_SECRET", "")
if _MIRTH_JWT_SECRET_ENV:
    MIRTH_JWT_SECRET = _MIRTH_JWT_SECRET_ENV
elif _django_settings.DEBUG:
    MIRTH_JWT_SECRET = "MIRTH_DEMO_SECRET_KEY"
else:
    raise ImproperlyConfigured(
        "MIRTH_JWT_SECRET env var is required when DJANGO_DEBUG is not set."
    )
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
@login_required
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
@login_required
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

    MAX_CSV_BYTES = 10 * 1024 * 1024  # 10 MB
    if upload.size and upload.size > MAX_CSV_BYTES:
        runs = PatientImportRun.objects.order_by("-created_at")[:20]
        return render(request, "patient_import.html", {
            "runs": runs,
            "error": f"File too large ({upload.size // 1024 // 1024} MB). Maximum allowed is 10 MB.",
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
@login_required
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
    from django.db.models import Count, Max

    latest_logs = HL7MessageLog.objects.only(
        "id", "created_at", "message_type", "processing_status", "patient_id", "trace_id"
    ).order_by("-created_at")[:5]
    total = HL7MessageLog.objects.count()

    trace_agg = TraceLog.objects.aggregate(
        trace_total=Count("id"),
        trace_errors=Count("id", filter=Q(error_count__gt=0)),
        latest_ts=Max("timestamp"),
    )
    trace_review_required = TraceLog.objects.filter(
        Q(status="FAILED") | Q(error_count__gt=0) | Q(steps__status__in=["WARN", "ERROR"])
    ).distinct().count()

    latest_trace_id = None
    if trace_agg["latest_ts"]:
        latest_trace = TraceLog.objects.only("trace_id").filter(
            timestamp=trace_agg["latest_ts"]
        ).first()
        latest_trace_id = latest_trace.trace_id if latest_trace else None

    return render(request, "home.html", {
        "total": total,
        "latest_logs": latest_logs,
        "trace_total": trace_agg["trace_total"],
        "trace_errors": trace_agg["trace_errors"],
        "trace_review_required": trace_review_required,
        "latest_trace_id": latest_trace_id,
    })



def hl7_playground(request):
    return render(request, "hl7_playground.html")

@login_required
def mirth_messages(request):
    from django.db.models import Count

    qs = HL7MessageLog.objects.order_by("-created_at")

    status_q = request.GET.get("status")
    if status_q:
        qs = qs.filter(processing_status=status_q)

    type_q = request.GET.get("type")
    if type_q:
        qs = qs.filter(message_type__icontains=type_q)

    trace_q = request.GET.get("trace_id")
    if trace_q:
        qs = qs.filter(trace_id__icontains=trace_q)

    logs = qs[:50]

    # Aggregate metrics over the full unfiltered table
    all_logs = HL7MessageLog.objects
    totals = all_logs.aggregate(
        total=Count("id"),
        with_encounter=Count("id", filter=Q(encounter_present=True)),
        transformed=Count("id", filter=Q(processing_status=HL7MessageLog.ProcessingStatus.TRANSFORMED)),
        failed=Count("id", filter=Q(processing_status=HL7MessageLog.ProcessingStatus.FAILED)),
        with_x12=Count("id", filter=Q(has_x12=True)),
    )

    status_choices = HL7MessageLog.ProcessingStatus.choices

    return render(request, "mirth_messages.html", {
        "logs": logs,
        "totals": totals,
        "status_choices": status_choices,
        "current_status": status_q or "",
        "current_type": type_q or "",
        "current_trace": trace_q or "",
    })
    

@login_required
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

    @extend_schema(
        summary="Transform HL7 v2 message to FHIR + X12",
        description=(
            "Accepts an HL7 v2 message (ADT, ORU, ORM, MDM) and returns the "
            "equivalent FHIR R4 resources plus X12 837/835 claim data where applicable."
        ),
        request=inline_serializer(
            name="HL7TransformRequest",
            fields={"hl7_message": drf_serializers.CharField()},
        ),
        responses={
            200: inline_serializer(
                name="HL7TransformResponse",
                fields={
                    "message_type": drf_serializers.CharField(),
                    "patient":       drf_serializers.DictField(required=False),
                    "encounter":     drf_serializers.DictField(required=False),
                    "x12_837":       drf_serializers.CharField(required=False),
                    "x12_835":       drf_serializers.CharField(required=False),
                    "claim_reconciliation": drf_serializers.DictField(required=False),
                },
            ),
            400: inline_serializer(
                name="HL7TransformError",
                fields={"error": drf_serializers.CharField()},
            ),
        },
        examples=[
            OpenApiExample(
                "ADT A01 Admission",
                request_only=True,
                value={"hl7_message": "MSH|^~\\&|MIRTH|HOSPITAL|RECV|FAC|202512181200||ADT^A01|MSG001|P|2.3\rPID|1||12345^^^MRN||DOE^JOHN||19800101|M\rPV1|1|I|W^101^1"},
            ),
        ],
        tags=["HL7 Transformation"],
    )
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
        errors, _ = validate_hl7_message(hl7_message)
        ack_code = "AE" if errors else "AA"
        result["ack"] = generate_ack(hl7_message, ack_code=ack_code)
        return Response(result, status=status.HTTP_200_OK)


    
class MirthHL7View(APIView):
    @extend_schema(
        summary="Mirth Connect inbound HL7 endpoint",
        description=(
            "JWT-authenticated endpoint for Mirth Connect channels. Validates the HL7 message, "
            "transforms it, persists an audit log, and returns an HL7 v2 ACK alongside JSON results."
        ),
        request=inline_serializer(
            name="MirthHL7Request",
            fields={
                "hl7_message":    drf_serializers.CharField(),
                "source_context": drf_serializers.DictField(required=False),
            },
        ),
        responses={
            200: inline_serializer(
                name="MirthHL7Response",
                fields={
                    "status":   drf_serializers.CharField(),
                    "trace_id": drf_serializers.CharField(),
                    "ack":      drf_serializers.CharField(),
                    "summary":  drf_serializers.DictField(),
                    "warnings": drf_serializers.ListField(child=drf_serializers.CharField()),
                },
            ),
            400: inline_serializer(
                name="MirthHL7Error",
                fields={
                    "status":         drf_serializers.CharField(),
                    "trace_id":       drf_serializers.CharField(),
                    "ack":            drf_serializers.CharField(),
                    "error_category": drf_serializers.CharField(),
                    "errors":         drf_serializers.ListField(child=drf_serializers.CharField()),
                },
            ),
        },
        tags=["Mirth Connect"],
    )
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

        data = {}
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
            return Response(
                {"status": "failed", "trace_id": trace_id, "error": "Missing or empty hl7_message"},
                status=status.HTTP_400_BAD_REQUEST,
            )

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

            ack = generate_ack(normalized, ack_code="AE", error_msg="; ".join(errors))
            return Response(
                {
                    "status": "failed",
                    "trace_id": trace_id,
                    "ack": ack,
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

        

        msg_log = HL7MessageLog.objects.create(
            trace_id=trace_id,
            source_system="MIRTH",
            source_context=source_context,
            message_type=summary.get("message_type") or "",
            message_profile=message_profile,
            trigger_event=trigger_event,
            raw_hl7=normalized,
            processing_status=HL7MessageLog.ProcessingStatus.TRANSFORMED,
            steps=steps,
            patient_id=patient_id,
            encounter_present=encounter_present,
            patient_class=patient_class,
            event_time=event_time,
            x12_length=x12_length,
            has_x12=has_x12,
            error_category=error_category,
            error_message=error_message,
        )

        # Persist claim lifecycle record for reconciliation report.
        # Only ADT messages with X12 output produce a claim.
        recon = result.get("claim_reconciliation")
        if has_x12 and recon:
            status_map = {"paid": ClaimRecord.ClaimStatus.PAID, "denied": ClaimRecord.ClaimStatus.DENIED}
            claim_status = status_map.get(recon.get("status"), ClaimRecord.ClaimStatus.SUBMITTED)
            ClaimRecord.objects.create(
                message_log=msg_log,
                trace_id=trace_id,
                claim_id=recon.get("claim_id", ""),
                patient_id=patient_id,
                status=claim_status,
                billed_amount=recon.get("billed_total", 0),
                paid_amount=recon.get("paid_amount", 0),
                patient_responsibility=recon.get("patient_responsibility", 0),
                balance_due=recon.get("balance_due_to_provider", 0),
                x12_837=result.get("x12_837") or "",
                x12_835=result.get("x12_835") or "",
            )

        # Dispatch FHIR webhooks to simulated downstream systems.
        # Runs after DB writes so a webhook failure never blocks the pipeline.
        dispatch_webhooks_for_result(result, trace_id)

        ack = generate_ack(normalized, ack_code="AA")
        return Response(
            {
                "status": "ok",
                "trace_id": trace_id,
                "ack": ack,
                "summary": summary,
                "warnings": warn_list,
                "fhir": result.get("fhir"),
                "x12_837": result.get("x12_837"),
            },
            status=status.HTTP_200_OK,
        )


@login_required
def webhook_delivery_log(request):
    """
    GET /webhooks/

    Shows every outbound FHIR webhook attempt — delivered, failed, or pending.
    Demonstrates the outbound side of the pipeline: after a successful HL7
    transform, the FHIR resource is pushed to downstream systems.

    In production this is how an ops team monitors delivery failures and
    triggers manual retries before the patient data goes stale downstream.
    """
    from django.db.models import Count

    qs = WebhookDelivery.objects.all()

    status_filter = request.GET.get("status")
    resource_filter = request.GET.get("resource_type")
    if status_filter in {s.value for s in WebhookDelivery.DeliveryStatus}:
        qs = qs.filter(status=status_filter)
    if resource_filter:
        qs = qs.filter(fhir_resource_type=resource_filter)

    totals = WebhookDelivery.objects.aggregate(
        total=Count("id"),
        delivered=Count("id", filter=Q(status=WebhookDelivery.DeliveryStatus.DELIVERED)),
        failed=Count("id", filter=Q(status=WebhookDelivery.DeliveryStatus.FAILED)),
        pending=Count("id", filter=Q(status=WebhookDelivery.DeliveryStatus.PENDING)),
    )

    resource_types = (
        WebhookDelivery.objects.values_list("fhir_resource_type", flat=True)
        .distinct()
        .order_by("fhir_resource_type")
    )

    return render(request, "webhook_log.html", {
        "deliveries": qs[:100],
        "totals": totals,
        "status_choices": WebhookDelivery.DeliveryStatus.choices,
        "current_status": status_filter,
        "resource_types": resource_types,
        "current_resource": resource_filter,
    })


@login_required
def claim_reconciliation_report(request):
    """
    GET /mirth/claims/reconciliation/

    Billing reconciliation dashboard: every claim that flowed through
    the Mirth pipeline, with billed vs paid vs denied totals.

    Key concept: this is the operational report a billing team checks
    daily to catch underpayments, denials, and unmatched claims.
    """
    from django.db.models import Sum, Count

    qs = ClaimRecord.objects.select_related("message_log").order_by("-created_at")

    # Filter by status if requested
    status_filter = request.GET.get("status")
    if status_filter in {s.value for s in ClaimRecord.ClaimStatus}:
        qs = qs.filter(status=status_filter)

    # Aggregate totals — one DB query instead of iterating in Python
    totals = ClaimRecord.objects.aggregate(
        total_claims=Count("id"),
        total_billed=Sum("billed_amount"),
        total_paid=Sum("paid_amount"),
        total_patient_resp=Sum("patient_responsibility"),
        total_balance_due=Sum("balance_due"),
        paid_count=Count("id", filter=Q(status=ClaimRecord.ClaimStatus.PAID)),
        denied_count=Count("id", filter=Q(status=ClaimRecord.ClaimStatus.DENIED)),
        partial_count=Count("id", filter=Q(status=ClaimRecord.ClaimStatus.PARTIAL)),
        submitted_count=Count("id", filter=Q(status=ClaimRecord.ClaimStatus.SUBMITTED)),
    )

    return render(request, "claim_reconciliation.html", {
        "claims": qs[:100],   # cap at 100 rows for demo
        "totals": totals,
        "status_choices": ClaimRecord.ClaimStatus.choices,
        "current_status": status_filter,
    })


@login_required
def retry_webhook(request, pk: int):
    """
    POST /webhooks/<pk>/retry/
    Re-attempts delivery of a failed or pending WebhookDelivery.
    Enforces max_retries limit.
    """
    from django.contrib import messages as flash

    delivery = get_object_or_404(WebhookDelivery, pk=pk)

    if delivery.attempt_count >= delivery.max_retries:
        flash.error(request, f"Max retries ({delivery.max_retries}) reached for delivery #{pk}.")
        return redirect("webhook-log")

    if delivery.status == WebhookDelivery.DeliveryStatus.DELIVERED:
        flash.info(request, f"Delivery #{pk} already succeeded.")
        return redirect("webhook-log")

    # Re-run delivery with same payload
    delivery.attempt_count += 1
    delivery.status = WebhookDelivery.DeliveryStatus.RETRYING
    delivery.next_retry_at = None
    delivery.save(update_fields=["attempt_count", "status", "next_retry_at"])

    # Simulate the retry attempt
    import time
    from django.utils import timezone
    from example.webhook_service import SIMULATED_ERRORS

    start = time.time()
    time.sleep(random.uniform(0.01, 0.05))
    success = random.random() < 0.80
    duration_ms = int((time.time() - start) * 1000)

    if success:
        delivery.status = WebhookDelivery.DeliveryStatus.DELIVERED
        delivery.response_code = 201
        delivery.delivered_at = timezone.now()
        delivery.error_detail = ""
        flash.success(request, f"Delivery #{pk} succeeded on retry #{delivery.attempt_count}.")
    else:
        delivery.status = WebhookDelivery.DeliveryStatus.FAILED
        delivery.response_code = 503
        delivery.error_detail = random.choice(SIMULATED_ERRORS)
        # Schedule next retry with exponential backoff (2^attempt minutes)
        from datetime import timedelta
        delay_minutes = 2 ** delivery.attempt_count
        delivery.next_retry_at = timezone.now() + timedelta(minutes=delay_minutes)
        flash.warning(request, f"Delivery #{pk} retry #{delivery.attempt_count} failed. Next retry in {delay_minutes}m.")

    delivery.duration_ms = duration_ms
    delivery.save(update_fields=[
        "status", "response_code", "delivered_at", "error_detail",
        "next_retry_at", "duration_ms",
    ])
    return redirect("webhook-log")


@login_required
def seed_demo_data_view(request):
    """
    POST /seed-demo-data/          — seed demo records
    POST /seed-demo-data/?clear=1  — wipe SEED records then re-seed
    Redirects to home with a Django messages flash.
    """
    from django.contrib import messages
    from example.seed_demo import seed_demo_data

    if request.method != "POST":
        return redirect("home")

    # Always clear and re-seed so timestamps stay current
    clear = True
    result = seed_demo_data(clear_existing=clear)

    if result.get("skipped"):
        messages.info(request, result["reason"])
    else:
        messages.success(
            request,
            f"Demo data seeded: {result['messages']} messages, "
            f"{result['claims']} claims, {result['webhooks']} webhooks.",
        )
    return redirect("home")


def guided_demo(request):
    """
    POST /guided-demo/
    Seeds fresh demo data (always clears first so timestamps are current),
    auto-logs the user in as the demo account if not authenticated,
    then redirects to the Mirth messages page — step 1 of the guided tour.
    The tour steps are embedded in the destination pages via a ?tour=1 param.
    """
    from django.contrib.auth import authenticate, login as auth_login
    from django.contrib import messages
    from example.seed_demo import seed_demo_data

    # Seed fresh data
    seed_demo_data(clear_existing=True)

    # Auto-login as demo user if not already authenticated
    if not request.user.is_authenticated:
        user = authenticate(request, username="demo", password="demo1234")
        if user:
            auth_login(request, user)

    messages.success(
        request,
        "Guided demo started — follow the tour steps highlighted on each page.",
    )
    return redirect("/mirth/messages/?tour=1")


def integration_specs(request):
    """
    GET /integrations/
    Integration Specifications documentation page.
    Pulls live stats from every model so the page reflects real data.
    """
    from adt.models import ADTMessage, DFTMessage
    from logtrace.models import TraceLog

    def _last(qs):
        obj = qs.order_by("-id").first()
        return obj.created_at if obj and hasattr(obj, "created_at") else None

    def _last_ts(qs):
        obj = qs.order_by("-id").first()
        return obj.timestamp if obj and hasattr(obj, "timestamp") else None

    # HL7 message type stats
    hl7_types = {}
    for mt in ("ADT", "ORU", "ORM", "DFT"):
        qs = HL7MessageLog.objects.filter(message_type__startswith=mt)
        hl7_types[mt] = {
            "count": qs.count(),
            "last":  _last(qs),
            "failed": qs.filter(processing_status="FAILED").count(),
        }

    # ADT / DFT native model stats
    adt_stats = {
        "count": ADTMessage.objects.count(),
        "last":  _last_ts(ADTMessage.objects.all()),
        "by_event": {
            ev: ADTMessage.objects.filter(event_type=ev).count()
            for ev in ("A01", "A02", "A03", "A08")
        },
    }
    dft_stats = {
        "count": DFTMessage.objects.count(),
        "last":  _last_ts(DFTMessage.objects.all()),
    }

    # FHIR stats (PatientRecord is the canonical patient store)
    fhir_stats = {
        "patient_count": PatientRecord.objects.count(),
        "last_patient":  _last(PatientRecord.objects.all()),
    }

    # X12 claim stats
    claim_stats = {
        "count": ClaimRecord.objects.count(),
        "paid":  ClaimRecord.objects.filter(status="PAID").count(),
        "denied": ClaimRecord.objects.filter(status="DENIED").count(),
        "last":  _last(ClaimRecord.objects.all()),
    }

    # Flat-file ingest stats (table may not exist on local SQLite before migration)
    try:
        from sftpingest.models import SFTPIngestRun
        sftp_stats = {
            "count":   SFTPIngestRun.objects.count(),
            "patient": SFTPIngestRun.objects.filter(schema_type="PATIENT").count(),
            "clinical": SFTPIngestRun.objects.filter(schema_type="CLINICAL").count(),
            "last":    _last(SFTPIngestRun.objects.all()),
        }
    except Exception:
        sftp_stats = {"count": 0, "patient": 0, "clinical": 0, "last": None}

    # TraceLog stats
    trace_stats = {
        "count": TraceLog.objects.count(),
        "last":  _last(TraceLog.objects.all()),
    }

    return render(request, "integration_specs.html", {
        "hl7_types":   hl7_types,
        "adt_stats":   adt_stats,
        "dft_stats":   dft_stats,
        "fhir_stats":  fhir_stats,
        "claim_stats": claim_stats,
        "sftp_stats":  sftp_stats,
        "trace_stats": trace_stats,
    })




def health(request):
    """
    GET /health/
    Returns 200 if the DB is reachable, 503 otherwise.
    Used by Vercel health checks and uptime monitors.
    """
    try:
        connection.ensure_connection()
        db_ok = True
    except Exception:
        db_ok = False

    payload = {
        "status": "ok" if db_ok else "degraded",
        "db": "ok" if db_ok else "error",
    }
    return JsonResponse(payload, status=200 if db_ok else 503)


def custom_404(request, exception=None):
    return render(request, "404.html", status=404)
