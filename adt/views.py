import logging

from django.db.models import Count, Q, Sum
from django.shortcuts import render
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter

from .dft_generator import generate_dft
from .dft_service import create_dft_from_adt
from .hl7_generator import generate_adt
from .models import ADTMessage, DFTChargeItem, DFTMessage
from .serializers import (
    ADTMessageSerializer,
    ADTTriggerSerializer,
    DFTMessageListSerializer,
    DFTMessageSerializer,
)

logger = logging.getLogger("adt")


# ── Pagination ────────────────────────────────────────────────────────────────

class ADTPagination(PageNumberPagination):
    page_size = 25


class DFTPagination(PageNumberPagination):
    page_size = 25


# ── ADT REST API ───────────────────────────────────────────────────────────────

class ADTTriggerView(APIView):
    @extend_schema(
        summary="Trigger an ADT event",
        description=(
            "Generates an HL7 v2.3 ADT message for the requested event type "
            "(A01 Admit, A02 Transfer, A03 Discharge, A08 Update), persists it, "
            "and automatically creates a downstream DFT^P03 billing message for "
            "A01 and A03 events, completing the ADT → DFT → X12 837P revenue "
            "cycle chain."
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
            raw_hl7    = generate_adt(patient_id=patient_id, event_type=event_type)
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

        # Auto-generate a DFT^P03 billing message for admit/discharge events.
        # A02 (transfer) and A08 (update) don't produce new charge transactions.
        if msg_status == ADTMessage.Status.GENERATED:
            dft = create_dft_from_adt(msg)
            if dft:
                logger.info(
                    "DFT^P03 auto-created: id=%s claim=%s for ADT id=%s",
                    dft.pk, dft.claim_id, msg.pk,
                )

        return Response(ADTMessageSerializer(msg).data, status=status.HTTP_201_CREATED)


class ADTMessageListAPI(ListAPIView):
    serializer_class = ADTMessageSerializer
    pagination_class = ADTPagination

    @extend_schema(
        summary="List ADT messages",
        parameters=[
            OpenApiParameter("event_type", str, description="Filter by event type (A01/A02/A03/A08)"),
            OpenApiParameter("status",     str, description="Filter by status"),
            OpenApiParameter("patient_id", str, description="Filter by patient MRN"),
        ],
        tags=["ADT Simulation"],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = ADTMessage.objects.all()
        if et  := self.request.query_params.get("event_type"):
            qs = qs.filter(event_type=et.upper())
        if st  := self.request.query_params.get("status"):
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


# ── DFT REST API ───────────────────────────────────────────────────────────────

class DFTMessageListAPI(ListAPIView):
    serializer_class = DFTMessageListSerializer
    pagination_class = DFTPagination

    @extend_schema(
        summary="List DFT billing messages",
        description=(
            "Returns DFT^P03 records with their charge summary. Filter by "
            "patient MRN or encounter ID to trace the full revenue cycle for "
            "a specific encounter."
        ),
        parameters=[
            OpenApiParameter("patient_id",   str, description="Filter by patient MRN"),
            OpenApiParameter("encounter_id", str, description="Filter by encounter ID"),
            OpenApiParameter("trigger_event",str, description="Filter by trigger event (A01/A03/MANUAL)"),
            OpenApiParameter("status",       str, description="Filter by status (GENERATED/SENT/FAILED)"),
        ],
        tags=["DFT Billing"],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = DFTMessage.objects.prefetch_related("charges").all()
        if pid := self.request.query_params.get("patient_id"):
            qs = qs.filter(patient_id__icontains=pid)
        if enc := self.request.query_params.get("encounter_id"):
            qs = qs.filter(encounter_id__icontains=enc)
        if te  := self.request.query_params.get("trigger_event"):
            qs = qs.filter(trigger_event=te.upper())
        if st  := self.request.query_params.get("status"):
            qs = qs.filter(status=st.upper())
        return qs


class DFTMessageDetailAPI(RetrieveAPIView):
    serializer_class = DFTMessageSerializer
    queryset         = DFTMessage.objects.prefetch_related("charges").all()

    @extend_schema(
        summary="Retrieve a single DFT message",
        description=(
            "Full DFT^P03 record including all FT1 charge line items and the "
            "generated X12 837P claim string. Demonstrates the complete mapping "
            "from HL7 financial transaction to EDI claim."
        ),
        tags=["DFT Billing"],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


# ── HTML UI views ──────────────────────────────────────────────────────────────

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

    messages = qs.select_related()[:100]

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

    # Annotate each ADT message with its linked DFT count for display
    adt_ids_with_dft = set(
        DFTMessage.objects.filter(adt_message__isnull=False)
        .values_list("adt_message_id", flat=True)
    )

    return render(request, "adt/adt_list.html", {
        "messages":         messages,
        "totals":           totals,
        "event_choices":    ADTMessage.EventType.choices,
        "status_choices":   ADTMessage.Status.choices,
        "current_event":    current_event,
        "current_status":   current_status,
        "current_pid":      current_pid,
        "adt_ids_with_dft": adt_ids_with_dft,
    })


def dft_list_page(request):
    """Revenue cycle dashboard: DFT messages, charge lines, and 837P links."""
    qs = DFTMessage.objects.prefetch_related("charges", "adt_message").all()

    current_pid    = request.GET.get("patient_id", "")
    current_enc    = request.GET.get("encounter_id", "")
    current_event  = request.GET.get("trigger_event", "")
    current_status = request.GET.get("status", "")

    if current_pid:
        qs = qs.filter(patient_id__icontains=current_pid)
    if current_enc:
        qs = qs.filter(encounter_id__icontains=current_enc)
    if current_event:
        qs = qs.filter(trigger_event=current_event.upper())
    if current_status:
        qs = qs.filter(status=current_status.upper())

    dft_messages = qs[:100]

    totals = DFTMessage.objects.aggregate(
        total=Count("id"),
        total_charges=Sum("total_charges"),
        a01_count=Count("id", filter=Q(trigger_event="A01")),
        a03_count=Count("id", filter=Q(trigger_event="A03")),
        failed=Count("id", filter=Q(status="FAILED")),
    )

    return render(request, "adt/dft_list.html", {
        "dft_messages":     dft_messages,
        "totals":           totals,
        "trigger_choices":  DFTMessage.TriggerEvent.choices,
        "status_choices":   DFTMessage.Status.choices,
        "current_pid":      current_pid,
        "current_enc":      current_enc,
        "current_event":    current_event,
        "current_status":   current_status,
    })
