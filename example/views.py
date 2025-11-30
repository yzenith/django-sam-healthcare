import json
from django.http import HttpResponseForbidden
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.renderers import JSONRenderer
from django.shortcuts import render 

from .serializers import HL7TransformRequestSerializer
from .hl7_utils import hl7_to_all

from .models import HL7MessageLog

def mirth_messages(request):
    logs = HL7MessageLog.objects.order_by("-created_at")[:20]
    return render(request, "mirth_messages.html", {"logs": logs})

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
            except ValueError:
                # Not valid JSON, fall back to raw body
                hl7_message = body
        else:
            # Non-JSON: treat the whole body as HL7 text
            hl7_message = body

        result = hl7_to_all(hl7_message)
        return Response(result, status=status.HTTP_200_OK)


class MirthHL7View(APIView):
    renderer_classes = [JSONRenderer]
    MIRTH_SECRET = "super-secret-demo-token"  # in real life use env var

    def post(self, request, *args, **kwargs):
        # 1) Read raw body
        body = request.body.decode("utf-8", errors="ignore").strip()

        key = request.headers.get("X-Integration-Key")
        if key != self.MIRTH_SECRET:
            return HttpResponseForbidden("Invalid integration key")

        # 2) Handle both plain text and JSON (future-proof)
        hl7_message = ""
        if request.content_type and "application/json" in request.content_type:
            try:
                data = json.loads(body)
                hl7_message = data.get("hl7_message", "")
            except ValueError:
                hl7_message = body
        else:
            hl7_message = body

        # 3) Transform HL7 → FHIR → 837
        result = hl7_to_all(hl7_message)

        # You can shape response specifically for Mirth
        return Response(
            {
                "status": "ok",
                "patientId": (result["patient"] or {}).get("id"),
                "hasEncounter": result["encounter"] is not None,
                "x12Length": len(result["x12_837"] or ""),
                "data": result,  # full payload if you want
            },
            status=status.HTTP_200_OK,
        )
