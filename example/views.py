import json
import os
import uuid
import warnings

from django.http import HttpResponseForbidden
import jwt
from datetime import datetime
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.renderers import JSONRenderer
from django.shortcuts import get_object_or_404, render 
from .hl7_utils import *

from .models import HL7MessageLog

# JWT settings – use env vars in real deployment
MIRTH_JWT_SECRET = os.environ.get("MIRTH_JWT_SECRET", "MIRTH_DEMO_SECRET_KEY")
MIRTH_JWT_ALG = "HS256"
MIRTH_JWT_AUD = "mirth-connector"
MIRTH_JWT_ISS = "django-sam-healthcare"

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
    logs = HL7MessageLog.objects.order_by("-created_at")[:20]
    return render(request, "mirth_messages.html", {"logs": logs})
    

def mirth_message_detail(request, pk):
    log = get_object_or_404(HL7MessageLog, pk=pk)

    # Re-run transform on the raw HL7 so we don't need to store JSON in DB
    transform_result = hl7_to_all(log.raw_hl7)
    patient = transform_result.get("patient")
    encounter = transform_result.get("encounter")
    x12_837 = transform_result.get("x12_837")


    context = {
        "log": log,
        "patient": patient,
        "encounter": encounter,
        "x12_837": x12_837,
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
    # 只用 JSONRenderer，不用 BrowsableAPIRenderer
    renderer_classes = [JSONRenderer]

    def post(self, request, *args, **kwargs):
        """
        Accepts either:
        1) JSON:  {"hl7_message": "<HL7 text>"}
        2) Plain text: raw HL7 message in the body
        """
        body = request.body.decode("utf-8", errors="ignore").strip()

        hl7_message = ""


        # Try JSON first
        if request.content_type and "application/json" in request.content_type:
            try:
                data = json.loads(body)
                hl7_message = data.get("hl7_message", "")

                if not hl7_message.startswith("MSH"):
                    return Response({"error": "Invalid HL7 message"}, status=400)  
                if "ADT" not in hl7_message:
                    # warn but still process
                    pass
                
            except ValueError:
                # Not valid JSON, fall back to raw body
                hl7_message = body
        else:
            # Non-JSON: treat the whole body as HL7 text
            hl7_message = body

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
        errors, warnings = validate_hl7_message(normalized)
        summary = extract_hl7_summary(normalized) or {}
        message_profile = build_message_profile(summary.get("message_type") or "")
        trigger_event = build_trigger_event(summary.get("message_type") or "")

        incoming_source_context = request.data.get("source_context") or {}
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
                    "warnings": warnings,
                    "summary": summary,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        steps.append({"sequence": 2, "step": "VALIDATION", "status": "OK"})
        result = hl7_to_all(normalized)
        steps.append({"sequence": 3, "step": "TRANSFORM", "status": "OK"})

        # validate 通过后，加入一个轻量判断（不挡请求，只写 steps/warnings）：
        if not source_context.get("sending_application") or not source_context.get("sending_facility"):
            warnings.append("Missing MSH-3/4 (sending application/facility); common facility variance.")


        

        HL7MessageLog.objects.create(
            trace_id=trace_id,
            source_system="MIRTH",
            source_context=source_context,
            message_type=summary.get("message_type") or "",
            message_profile=message_profile,
            trigger_event=trigger_event,
            raw_hl7=normalized,
            processing_status=HL7MessageLog.ProcessingStatus.TRANSFORMED,
            error_category=HL7MessageLog.ErrorCategory.NONE,
            error_message="",
            steps=steps,
            has_x12=bool(result.get("x12_837")),
        )

        return Response(
            {
                "status": "ok",
                "trace_id": trace_id,
                "summary": summary,
                "warnings": warnings,
                "fhir": result.get("fhir"),
                "x12_837": result.get("x12_837"),
            },
            status=status.HTTP_200_OK,
        )

