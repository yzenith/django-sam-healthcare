from urllib.parse import urlencode
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.renderers import TemplateHTMLRenderer
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
import json
from django.shortcuts import redirect


from .models import TraceLog
from .serializers import IngestSerializer, TraceLogListSerializer, TraceLogDetailSerializer
from .services import ingest_payload


class IngestAPIView(APIView):
    def post(self, request):
        ser = IngestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        log = ingest_payload(
            raw_payload=ser.validated_data["raw_payload"],
            declared_input_type=ser.validated_data.get("input_type"),
            output_type=ser.validated_data.get("output_type", "FHIR_JSON"),
            meta=ser.validated_data.get("meta", {}),
        )
        return Response({"trace_id": log.trace_id}, status=status.HTTP_201_CREATED)


class TraceLogListAPI(ListAPIView):
    serializer_class = TraceLogListSerializer

    def get_queryset(self):
        qs = TraceLog.objects.all().order_by("-timestamp")
        input_type = self.request.query_params.get("input_type")
        status_q = self.request.query_params.get("status")
        has_errors = self.request.query_params.get("has_errors")

        if input_type:
            qs = qs.filter(input_type=input_type)
        if status_q:
            qs = qs.filter(status=status_q)
        if has_errors in {"true", "1"}:
            qs = qs.filter(error_count__gt=0)

        return qs


class TraceLogDetailAPI(RetrieveAPIView):
    serializer_class = TraceLogDetailSerializer
    lookup_field = "trace_id"
    queryset = TraceLog.objects.prefetch_related("steps").all()


class TraceLogPagePagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 200


class TraceLogListPage(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = "trace/log_list.html"
    pagination_class = TraceLogPagePagination

    def get(self, request):
        qs = TraceLog.objects.all().order_by("-timestamp")

        # Filters (same style as your API, plus trace_id contains)
        trace_id = request.query_params.get("trace_id")
        input_type = request.query_params.get("input_type")
        status_q = request.query_params.get("status")
        has_errors = request.query_params.get("has_errors")

        if trace_id:
            qs = qs.filter(trace_id__icontains=trace_id)
        if input_type:
            qs = qs.filter(input_type=input_type)
        if status_q:
            qs = qs.filter(status=status_q)
        if has_errors == "1":
            qs = qs.filter(error_count__gt=0)
        if has_errors == "0":
            qs = qs.filter(error_count=0)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)

        # Build querystring excluding page (for pagination links)
        q = request.query_params.copy()
        q.pop("page", None)
        querystring = urlencode(q)

        base_qs = TraceLog.objects.all()
        context = {
            "logs": page,
            "is_paginated": paginator.page is not None,
            "page_obj": paginator.page,
            "total_count": base_qs.count(),
            "error_count": base_qs.filter(error_count__gt=0).count(),
            "input_types": ["HL7", "JSON", "EDI", "OTHER"],
            "statuses": ["RECEIVED", "PROCESSED", "FAILED"],
            "querystring": querystring,
        }
        return Response(context)


class TraceLogDetailPage(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = "trace/log_detail.html"

    def get(self, request, trace_id: str):
        log = get_object_or_404(
            TraceLog.objects.prefetch_related("steps"),
            trace_id=trace_id
        )
        context = {
            "log": log,
            "steps": log.steps.all(),
        }
        return Response(context)


class TraceIngestPage(APIView):
    """
    Simple HTML form to trigger trace ingestion (creates TraceLog).
    """
    renderer_classes = [TemplateHTMLRenderer]
    template_name = "trace/ingest.html"
    permission_classes = [AllowAny]

    def get(self, request):
        # Optional: provide a default HL7 example for convenience
        sample_hl7 = (
            "MSH|^~\\&|SENDING|FACILITY|RECEIVING|FACILITY|202501011230||ADT^A01|MSG00001|P|2.3\r"
            "PID|||12345^^^MRN||DOE^JOHN||19800101|M\r"
            "PV1||I|W^389^1||||1234^PROVIDER^TEST\r"
        )
        return Response({
            "default_input_type": "HL7",
            "default_output_type": "FHIR_JSON",
            "default_raw_payload": sample_hl7,
            "default_meta": json.dumps({"source": "trace_ui"}, indent=2),
        })

    def post(self, request):
        raw_payload = (request.data.get("raw_payload") or "").strip()
        input_type = (request.data.get("input_type") or "").strip() or None
        output_type = (request.data.get("output_type") or "FHIR_JSON").strip()

        meta_raw = request.data.get("meta") or "{}"
        try:
            meta = json.loads(meta_raw) if isinstance(meta_raw, str) else meta_raw
        except Exception:
            # If meta JSON is invalid, re-render with an error message
            return Response(
                {
                    "error": "Meta must be valid JSON.",
                    "default_input_type": input_type or "HL7",
                    "default_output_type": output_type,
                    "default_raw_payload": raw_payload,
                    "default_meta": meta_raw,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not raw_payload:
            return Response(
                {
                    "error": "raw_payload is required.",
                    "default_input_type": input_type or "HL7",
                    "default_output_type": output_type,
                    "default_raw_payload": raw_payload,
                    "default_meta": json.dumps(meta, indent=2),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        log = ingest_payload(
            raw_payload=raw_payload,
            declared_input_type=input_type,
            output_type=output_type,
            meta=meta,
        )

        # Redirect to your trace detail UI
        return redirect("trace-detail-page", trace_id=log.trace_id)