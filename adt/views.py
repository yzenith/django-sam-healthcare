import logging

from django.shortcuts import get_object_or_404, render
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter

from .hl7_generator import generate_adt
from .models import ADTMessage
from .serializers import ADTMessageSerializer, ADTTriggerSerializer

logger = logging.getLogger("adt")

# ── Pagination ────────────────────────────────────────────────────────────────

class ADTPagination(PageNumberPagination):
    page_size = 25


# ── REST API views ─────────────────────────────────────────────────────────────

class ADTTriggerView(APIView):
    @extend_schema(
        summary="Trigger an ADT event",
        description=(
            "Generates an HL7 v2.3 ADT message for the requested event type "
            "(A01 Admit, A02 Transfer, A03 Discharge, A08 Update), persists it "
            "to the database, and returns the stored record."
        ),
        request=ADTTriggerSerializer,
        responses={201: ADTMessageSerializer},
        tags=["ADT Simulation"],
    )
    def post(self, request):
        ser = ADTTriggerSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        patient_id = ser.validated_data["patient_id"]
        event_type = ser.validated_data["event_type"]
        note       = ser.validated_data.get("note", "")

        try:
            raw_hl7 = generate_adt(patient_id=patient_id, event_type=event_type)
            msg_status = ADTMessage.Status.GENERATED
        except Exception as exc:
            logger.exception("HL7 generation failed for %s %s", event_type, patient_id)
            msg_status = ADTMessage.Status.FAILED
            raw_hl7    = ""
            note       = str(exc)

        msg = ADTMessage.objects.create(
            patient_id=patient_id,
            event_type=event_type,
            raw_hl7=raw_hl7,
            status=msg_status,
            note=note,
        )
        logger.info("ADT^%s generated for patient=%s id=%s", event_type, patient_id, msg.pk)

        out = ADTMessageSerializer(msg)
        return Response(out.data, status=status.HTTP_201_CREATED)


class ADTMessageListAPI(ListAPIView):
    serializer_class = ADTMessageSerializer
    pagination_class = ADTPagination

    @extend_schema(
        summary="List ADT messages",
        parameters=[
            OpenApiParameter("event_type", str, description="Filter by event type (A01/A02/A03/A08)"),
            OpenApiParameter("status",     str, description="Filter by status (GENERATED/SENT/FAILED)"),
            OpenApiParameter("patient_id", str, description="Filter by patient MRN"),
        ],
        tags=["ADT Simulation"],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = ADTMessage.objects.all()
        if et := self.request.query_params.get("event_type"):
            qs = qs.filter(event_type=et.upper())
        if st := self.request.query_params.get("status"):
            qs = qs.filter(status=st.upper())
        if pid := self.request.query_params.get("patient_id"):
            qs = qs.filter(patient_id__icontains=pid)
        return qs


class ADTMessageDetailAPI(RetrieveAPIView):
    serializer_class = ADTMessageSerializer
    queryset         = ADTMessage.objects.all()

    @extend_schema(
        summary="Retrieve a single ADT message",
        tags=["ADT Simulation"],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


# ── HTML UI view ───────────────────────────────────────────────────────────────

def adt_list_page(request):
    """HTML dashboard listing recent ADT messages with filter controls."""
    qs = ADTMessage.objects.all()

    current_event  = request.GET.get("event_type", "")
    current_status = request.GET.get("status", "")
    current_pid    = request.GET.get("patient_id", "")

    if current_event:
        qs = qs.filter(event_type=current_event.upper())
    if current_status:
        qs = qs.filter(status=current_status.upper())
    if current_pid:
        qs = qs.filter(patient_id__icontains=current_pid)

    messages = qs[:100]

    totals = {
        "total":     ADTMessage.objects.count(),
        "generated": ADTMessage.objects.filter(status=ADTMessage.Status.GENERATED).count(),
        "sent":      ADTMessage.objects.filter(status=ADTMessage.Status.SENT).count(),
        "failed":    ADTMessage.objects.filter(status=ADTMessage.Status.FAILED).count(),
        "a01":       ADTMessage.objects.filter(event_type=ADTMessage.EventType.A01).count(),
        "a02":       ADTMessage.objects.filter(event_type=ADTMessage.EventType.A02).count(),
        "a03":       ADTMessage.objects.filter(event_type=ADTMessage.EventType.A03).count(),
        "a08":       ADTMessage.objects.filter(event_type=ADTMessage.EventType.A08).count(),
    }

    return render(request, "adt/adt_list.html", {
        "messages":       messages,
        "totals":         totals,
        "event_choices":  ADTMessage.EventType.choices,
        "status_choices": ADTMessage.Status.choices,
        "current_event":  current_event,
        "current_status": current_status,
        "current_pid":    current_pid,
    })
