import json
import os
import jwt
from datetime import datetime, timedelta
from django.http import HttpResponseForbidden
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.renderers import JSONRenderer
from django.shortcuts import get_object_or_404, render 

from .serializers import HL7TransformRequestSerializer
from .hl7_utils import hl7_oru_to_fhir, hl7_to_all

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
        # 1) Very simple auth
        if request.headers.get("X-Integration-Key") != "super-secret-demo-token":  # in real life use env var
            return HttpResponseForbidden("Invalid integration key")

        # 2) Read raw body (plain text or JSON)
        body = request.body.decode("utf-8", errors="ignore").strip()
        hl7_message = body
        if "application/json" in (request.content_type or ""):
            try:
                data = json.loads(body)
                hl7_message = data.get("hl7_message", body)
            except ValueError:
                hl7_message = body

        # 3) Transform HL7 → (patient, encounter, x12)
        result = hl7_to_all(hl7_message)
        patient = result.get("patient") or {}
        encounter = result.get("encounter")
        x12 = result.get("x12_837") or ""

        # 4) ✅ SAVE LOG TO DB
        log = HL7MessageLog.objects.create(
            source_system="MIRTH",
            message_type="ADT-A01",
            raw_hl7=hl7_message,
            patient_id=patient.get("id") or "",
            encounter_present=bool(encounter),
            x12_length=len(x12),
        )

        # 5) Return summary to Mirth
        return Response(
            {
                "status": "ok",
                "log_id": log.id,
                "patientId": log.patient_id,
                "hasEncounter": log.encounter_present,
                "x12Length": log.x12_length,
            },
            status=status.HTTP_200_OK,
        )