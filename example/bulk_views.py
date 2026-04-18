"""
example/bulk_views.py

FHIR Bulk Data Access (FHIR R4 Bulk Data IG v2.0).

CMS-9115-F and CMS-0057-F require payers and providers to support bulk
data export so patients and third-party apps can retrieve their complete
health history in NDJSON format.

The async polling pattern:
  1. Client sends GET /fhir/Patient/$export
     → 202 Accepted + Content-Location: /fhir/bulkstatus/<job_id>/
  2. Client polls GET /fhir/bulkstatus/<job_id>/
     → 202 while in progress, 200 with manifest when complete
  3. Client downloads NDJSON files listed in manifest
     → GET /fhir/bulkfiles/<job_id>/<ResourceType>.ndjson

On Vercel (serverless) we process synchronously at request time since
the demo dataset is small. A production deployment would use Celery/SQS
to stream large datasets asynchronously.

Endpoints registered in example/urls.py:
  GET /fhir/Patient/$export              Initiate patient-level export
  GET /fhir/bulkstatus/<job_id>/         Poll export status
  GET /fhir/bulkfiles/<job_id>/<fname>/  Download NDJSON file
"""

import json
import uuid as _uuid

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from .models import BulkExportJob, HL7MessageLog
from .hl7_utils import hl7_to_all, hl7_oru_to_fhir


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _oo_error(code: str, diagnostics: str, status: int = 404) -> JsonResponse:
    """Return a FHIR OperationOutcome for error responses."""
    return JsonResponse({
        "resourceType": "OperationOutcome",
        "issue": [{"severity": "error", "code": code, "diagnostics": diagnostics}],
    }, status=status, content_type="application/fhir+json")


# ---------------------------------------------------------------------------
# $export endpoint
# ---------------------------------------------------------------------------

@login_required
@require_GET
def bulk_export_patient(request):
    """
    GET /fhir/Patient/$export

    Initiates an asynchronous bulk export of FHIR Patient resources (and
    optionally Encounter, DiagnosticReport via _type parameter).

    Query parameters:
      _since=<FHIR datetime>         Only resources updated after this date
      _type=Patient,Encounter,...    Resource types (default: Patient)
      _outputFormat=application/fhir+ndjson  (only NDJSON supported)

    Response: 202 Accepted + Content-Location header pointing to status URL.
    Prefer: respond-async header is respected but not required.
    """
    output_format = request.GET.get("_outputFormat", "application/fhir+ndjson")
    if output_format not in ("application/fhir+ndjson", "ndjson", "application/ndjson"):
        return _oo_error("not-supported", f"Unsupported _outputFormat: {output_format}", 400)

    since_str = request.GET.get("_since", "").strip()
    types_param = [t.strip() for t in request.GET.get("_type", "Patient").split(",") if t.strip()]
    supported_types = {"Patient", "Encounter", "DiagnosticReport"}
    types_param = [t for t in types_param if t in supported_types] or ["Patient"]

    since = None
    if since_str:
        try:
            since = timezone.datetime.fromisoformat(since_str.replace("Z", "+00:00"))
        except ValueError:
            return _oo_error("invalid", f"Invalid _since format: {since_str}", 400)

    # Process synchronously (Vercel serverless — no background workers)
    qs = HL7MessageLog.objects.exclude(raw_hl7="").order_by("-created_at")
    if since:
        qs = qs.filter(created_at__gte=since)

    patient_resources: list[dict] = []
    encounter_resources: list[dict] = []
    report_resources: list[dict] = []
    seen_patients: set = set()

    for log in qs[:500]:
        try:
            if log.message_type.startswith("ORU"):
                result = hl7_oru_to_fhir(log.raw_hl7)
                if "DiagnosticReport" in types_param and result.get("report"):
                    report_resources.append(result["report"])
                continue
            result = hl7_to_all(log.raw_hl7)
        except Exception:
            continue

        if "Patient" in types_param and result.get("patient"):
            pid = log.patient_id or result["patient"].get("id", "")
            if pid and pid not in seen_patients:
                patient = result["patient"]
                patient.setdefault("id", pid)
                seen_patients.add(pid)
                patient_resources.append(patient)

        if "Encounter" in types_param and result.get("encounter") and log.encounter_present:
            enc = result["encounter"]
            enc.setdefault("id", f"enc-{log.pk}")
            encounter_resources.append(enc)

    # Serialise to NDJSON lines and store in the job record
    ndjson_data: dict[str, list[str]] = {}
    output_files: list[dict] = []
    base_files_url = request.build_absolute_uri("/fhir/bulkfiles/")

    placeholder = "{job_id}"
    for rtype, resources in [
        ("Patient", patient_resources),
        ("Encounter", encounter_resources),
        ("DiagnosticReport", report_resources),
    ]:
        if resources and rtype in types_param:
            ndjson_data[rtype] = [json.dumps(r) for r in resources]
            output_files.append({
                "type": rtype,
                "url": f"{base_files_url}{placeholder}/{rtype}.ndjson",
                "count": len(resources),
            })

    job = BulkExportJob.objects.create(
        resource_type=",".join(types_param),
        status=BulkExportJob.Status.COMPLETE,
        output_files=output_files,
        ndjson_data=ndjson_data,
        since=since,
        requested_by=request.user.username,
        completed_at=timezone.now(),
    )

    job_id_str = str(job.job_id)
    for f in job.output_files:
        f["url"] = f["url"].replace(placeholder, job_id_str)
    job.save(update_fields=["output_files"])

    status_url = request.build_absolute_uri(f"/fhir/bulkstatus/{job_id_str}/")
    response = HttpResponse(status=202)
    response["Content-Location"] = status_url
    return response


# ---------------------------------------------------------------------------
# Status polling
# ---------------------------------------------------------------------------

@login_required
@require_GET
def bulk_export_status(request, job_id: str):
    """
    GET /fhir/bulkstatus/<job_id>/

    Returns 202 while in-progress, 200 with NDJSON manifest when complete.
    Per spec, completed jobs include an 'output' array and 'transactionTime'.
    """
    try:
        job = BulkExportJob.objects.get(job_id=job_id)
    except BulkExportJob.DoesNotExist:
        return _oo_error("not-found", f"Export job {job_id} not found")

    if job.status in (BulkExportJob.Status.PENDING, BulkExportJob.Status.RUNNING):
        return HttpResponse(status=202, headers={"X-Progress": "processing"})

    if job.status == BulkExportJob.Status.ERROR:
        return _oo_error("exception", job.error or "Export failed", 500)

    manifest = {
        "transactionTime": (job.completed_at or job.created_at).isoformat(),
        "request": request.build_absolute_uri("/fhir/Patient/$export"),
        "requiresAccessToken": True,
        "output": job.output_files,
        "error": [],
    }
    r = JsonResponse(manifest, content_type="application/json")
    r["Expires"] = "Mon, 01 Jan 2099 00:00:00 GMT"
    return r


# ---------------------------------------------------------------------------
# NDJSON file download
# ---------------------------------------------------------------------------

@login_required
@require_GET
def bulk_export_file(request, job_id: str, filename: str):
    """
    GET /fhir/bulkfiles/<job_id>/<filename>/

    Serves the NDJSON file produced by a completed bulk export job.
    filename format: <ResourceType>.ndjson (e.g. Patient.ndjson)
    """
    try:
        job = BulkExportJob.objects.get(job_id=job_id, status=BulkExportJob.Status.COMPLETE)
    except BulkExportJob.DoesNotExist:
        return _oo_error("not-found", f"Export job {job_id} not found or not complete")

    resource_type = filename.replace(".ndjson", "")
    lines = job.ndjson_data.get(resource_type, [])
    content = "\n".join(lines)
    r = HttpResponse(content, content_type="application/fhir+ndjson")
    r["Content-Disposition"] = f'attachment; filename="{filename}"'
    return r
