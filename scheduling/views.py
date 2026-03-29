import logging
import uuid
import random
from datetime import datetime, timedelta

from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import generics

from .models import SIUMessage
from .hl7_generator import generate_siu
from .serializers import SIUTriggerSerializer, SIUMessageSerializer, SIUMessageListSerializer

logger = logging.getLogger("scheduling")

_LOCATIONS  = ["CLINIC-1", "CLINIC-2", "RADIOLOGY", "LAB", "TELEHEALTH", "ED-BAY-4"]
_PROVIDERS  = [
    ("PROV-101", "Dr. Alice Chen"),
    ("PROV-102", "Dr. Marcus Webb"),
    ("PROV-103", "Dr. Priya Nair"),
    ("PROV-104", "Dr. James Okafor"),
]


# ── REST ──────────────────────────────────────────────────────────────────────

class SIUTriggerView(APIView):
    """
    POST /api/scheduling/trigger/

    Generates an HL7 v2.3 SIU message for the given patient / event type
    and stores it as a SIUMessage.
    """

    def post(self, request):
        serializer = SIUTriggerSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        data = serializer.validated_data
        prov_id, prov_name = random.choice(_PROVIDERS)

        appt_id = data.get("appointment_id") or f"APPT-{uuid.uuid4().hex[:8].upper()}"

        raw_hl7 = generate_siu(
            patient_id       = data["patient_id"],
            event_type       = data["event_type"],
            appointment_id   = appt_id,
            appointment_dt   = data["appointment_dt"],
            duration_minutes = data["duration_minutes"],
            appointment_type = data["appointment_type"],
            provider_id      = data["provider_id"]   or prov_id,
            provider_name    = data["provider_name"] or prov_name,
            location         = data["location"]      or random.choice(_LOCATIONS),
            reason           = data["reason"],
            note             = data["note"],
        )

        msg = SIUMessage.objects.create(
            patient_id       = data["patient_id"],
            appointment_id   = appt_id,
            event_type       = data["event_type"],
            appointment_dt   = data["appointment_dt"],
            duration_minutes = data["duration_minutes"],
            appointment_type = data["appointment_type"],
            provider_id      = data["provider_id"]   or prov_id,
            provider_name    = data["provider_name"] or prov_name,
            location         = data["location"]      or random.choice(_LOCATIONS),
            reason           = data["reason"],
            note             = data["note"],
            raw_hl7          = raw_hl7,
            status           = SIUMessage.Status.GENERATED,
        )

        logger.info(
            "siu_generated event=%s patient=%s appt=%s",
            data["event_type"], data["patient_id"], appt_id,
        )
        return Response(SIUMessageSerializer(msg).data, status=201)


class SIUMessageListAPI(generics.ListAPIView):
    """GET /api/scheduling/messages/"""
    queryset         = SIUMessage.objects.all()
    serializer_class = SIUMessageListSerializer


class SIUMessageDetailAPI(generics.RetrieveAPIView):
    """GET /api/scheduling/messages/<pk>/"""
    queryset         = SIUMessage.objects.all()
    serializer_class = SIUMessageSerializer


# ── HTML ──────────────────────────────────────────────────────────────────────

def siu_list_page(request):
    """GET /scheduling/ — SIU simulation dashboard."""
    messages = SIUMessage.objects.all()[:50]
    stats = {
        "total":     SIUMessage.objects.count(),
        "s12":       SIUMessage.objects.filter(event_type="S12").count(),
        "s14":       SIUMessage.objects.filter(event_type="S14").count(),
        "s15":       SIUMessage.objects.filter(event_type="S15").count(),
    }
    # Suggest a future appointment time ~2 days from now rounded to the hour
    default_dt = (datetime.utcnow() + timedelta(days=2)).replace(
        minute=0, second=0, microsecond=0
    ).strftime("%Y-%m-%dT%H:%M")

    return render(request, "scheduling/siu_list.html", {
        "messages":   messages,
        "stats":      stats,
        "default_dt": default_dt,
        "providers":  _PROVIDERS,
        "locations":  _LOCATIONS,
        "appt_types": SIUMessage.AppointmentType.choices,
    })
