"""
sftpingest/views.py
~~~~~~~~~~~~~~~~~~~
REST upload endpoint + HTML UI views for the simulated SFTP ingest pipeline.

Endpoints
---------
REST
  POST /api/sftp/upload/           Upload a flat file; returns ParseResult + run summary.
  GET  /api/sftp/runs/             List all ingest runs (paginated, most-recent first).
  GET  /api/sftp/runs/<pk>/        Detail for one run (includes validation_errors).

HTML
  GET  /sftp/                      Upload page with SFTP framing + recent-runs table.
  GET  /sftp/<pk>/                 Run detail page with error breakdown.
"""

import logging
import time

from django.db import transaction
from django.shortcuts import render, get_object_or_404
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import generics

from example.models import PatientRecord
from .models import SFTPIngestRun, ClinicalRecord
from .parser import parse_flat_file, MAX_FILE_BYTES
from .serializers import SFTPIngestRunSerializer, SFTPIngestRunListSerializer

logger = logging.getLogger("sftpingest")


# ── REST ──────────────────────────────────────────────────────────────────────

class SFTPUploadView(APIView):
    """
    POST /api/sftp/upload/

    Accepts a multipart file field named ``file``.
    Auto-detects delimiter and schema, validates every row, and persists
    clean records to PatientRecord (PATIENT schema) or ClinicalRecord (CLINICAL).

    Returns the full SFTPIngestRun JSON, including validation_errors.
    """
    parser_classes = [MultiPartParser]

    def post(self, request):
        upload = request.FILES.get("file")
        if not upload:
            return Response({"detail": "No file provided. POST with field name 'file'."}, status=400)

        if upload.size > MAX_FILE_BYTES:
            return Response(
                {"detail": f"File too large. Maximum allowed is 20 MB (got {upload.size} bytes)."},
                status=400,
            )

        filename = upload.name or "unknown.csv"
        content  = upload.read()

        t0     = time.monotonic()
        result = parse_flat_file(content, filename)
        parse_ms = int((time.monotonic() - t0) * 1000)

        # ── Fatal parse error (encoding, empty file, unknown schema) ──────────
        if result.fatal_error:
            run = SFTPIngestRun.objects.create(
                filename           = filename,
                status             = SFTPIngestRun.Status.FAILED,
                schema_type        = result.schema_type,
                detected_delimiter = result.delimiter_name,
                error_message      = result.fatal_error,
            )
            logger.warning("sftp_ingest fatal filename=%s error=%s", filename, result.fatal_error)
            return Response(SFTPIngestRunSerializer(run).data, status=422)

        # ── Persist valid records ─────────────────────────────────────────────
        inserted = updated = 0

        try:
            with transaction.atomic():
                if result.schema_type == "PATIENT":
                    for rec in result.valid_records:
                        obj, created = PatientRecord.objects.update_or_create(
                            mrn=rec["mrn"],
                            defaults={
                                "first_name": rec["first_name"],
                                "last_name":  rec["last_name"],
                                "dob":        rec["dob"],
                                "gender":     rec["gender"],
                                "address1":   rec["address1"],
                                "city":       rec["city"],
                                "state":      rec["state"],
                                "zip_code":   rec["zip_code"],
                            },
                        )
                        if created:
                            inserted += 1
                        else:
                            updated += 1

                    run = SFTPIngestRun.objects.create(
                        filename           = filename,
                        status             = SFTPIngestRun.Status.COMPLETED,
                        schema_type        = SFTPIngestRun.SchemaType.PATIENT,
                        detected_delimiter = result.delimiter_name,
                        total_rows         = result.total_rows,
                        valid_rows         = result.valid_rows,
                        inserted           = inserted,
                        updated            = updated,
                        rejected           = result.rejected_rows,
                        duplicates_in_file = result.duplicate_mrns,
                        validation_errors  = result.validation_errors,
                        processing_summary = {
                            "schema":          "PATIENT",
                            "delimiter":       result.delimiter_name,
                            "headers":         result.headers,
                            "parse_ms":        parse_ms,
                            "total_rows":      result.total_rows,
                            "valid_rows":      result.valid_rows,
                            "inserted":        inserted,
                            "updated":         updated,
                            "rejected":        result.rejected_rows,
                            "duplicates":      result.duplicate_mrns,
                            "error_count":     len(result.validation_errors),
                        },
                    )

                else:  # CLINICAL
                    run = SFTPIngestRun.objects.create(
                        filename           = filename,
                        status             = SFTPIngestRun.Status.COMPLETED,
                        schema_type        = SFTPIngestRun.SchemaType.CLINICAL,
                        detected_delimiter = result.delimiter_name,
                        total_rows         = result.total_rows,
                        valid_rows         = result.valid_rows,
                        inserted           = result.valid_rows,
                        updated            = 0,
                        rejected           = result.rejected_rows,
                        duplicates_in_file = result.duplicate_mrns,
                        validation_errors  = result.validation_errors,
                        processing_summary = {
                            "schema":          "CLINICAL",
                            "delimiter":       result.delimiter_name,
                            "headers":         result.headers,
                            "parse_ms":        parse_ms,
                            "total_rows":      result.total_rows,
                            "valid_rows":      result.valid_rows,
                            "inserted":        result.valid_rows,
                            "updated":         0,
                            "rejected":        result.rejected_rows,
                            "duplicates":      result.duplicate_mrns,
                            "error_count":     len(result.validation_errors),
                        },
                    )
                    inserted = result.valid_rows
                    ClinicalRecord.objects.bulk_create([
                        ClinicalRecord(
                            ingest_run     = run,
                            mrn            = rec["mrn"],
                            visit_date     = rec["visit_date"],
                            visit_type     = rec["visit_type"],
                            diagnosis_code = rec["diagnosis_code"],
                            procedure_code = rec["procedure_code"],
                            provider_id    = rec["provider_id"],
                            facility_code  = rec["facility_code"],
                            notes          = rec["notes"],
                        )
                        for rec in result.valid_records
                    ])

        except Exception as exc:
            logger.exception("sftp_ingest persist error filename=%s", filename)
            run = SFTPIngestRun.objects.create(
                filename      = filename,
                status        = SFTPIngestRun.Status.FAILED,
                schema_type   = result.schema_type,
                detected_delimiter = result.delimiter_name,
                error_message = str(exc),
            )
            return Response(SFTPIngestRunSerializer(run).data, status=500)

        logger.info(
            "sftp_ingest complete filename=%s schema=%s inserted=%d updated=%d rejected=%d ms=%d",
            filename, result.schema_type, inserted, updated, result.rejected_rows, parse_ms,
        )
        return Response(SFTPIngestRunSerializer(run).data, status=201)


class SFTPRunListAPI(generics.ListAPIView):
    """GET /api/sftp/runs/ — paginated list of all ingest runs."""
    queryset         = SFTPIngestRun.objects.all()
    serializer_class = SFTPIngestRunListSerializer


class SFTPRunDetailAPI(generics.RetrieveAPIView):
    """GET /api/sftp/runs/<pk>/ — full run detail with validation errors."""
    queryset         = SFTPIngestRun.objects.all()
    serializer_class = SFTPIngestRunSerializer


# ── HTML ──────────────────────────────────────────────────────────────────────

def sftp_upload_page(request):
    """GET /sftp/ — upload form + recent runs table."""
    recent_runs = SFTPIngestRun.objects.all()[:20]
    return render(request, "sftpingest/upload.html", {"recent_runs": recent_runs})


def sftp_run_detail_page(request, pk):
    """GET /sftp/<pk>/ — single run detail with error breakdown."""
    run = get_object_or_404(SFTPIngestRun, pk=pk)
    clinical_records = (
        run.clinical_records.all()[:50]
        if run.schema_type == SFTPIngestRun.SchemaType.CLINICAL
        else []
    )
    return render(request, "sftpingest/run_detail.html", {
        "run": run,
        "clinical_records": clinical_records,
    })
