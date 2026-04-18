"""
example/fhir_views.py

FHIR R4 REST API — read-only, US Core aligned.

Endpoints:
  GET /fhir/                          FHIR CapabilityStatement (metadata)
  GET /fhir/Patient/                  Search patients (Bundle)
  GET /fhir/Patient/<id>/             Read single patient
  GET /fhir/Encounter/                Search encounters (Bundle)
  GET /fhir/Encounter/<id>/           Read single encounter
  GET /fhir/DiagnosticReport/         Search diagnostic reports (Bundle)

All responses are FHIR R4 JSON.  Authentication: same session auth as the
rest of the app (login_required).  In a production SMART on FHIR deployment
these would be protected by OAuth2 bearer tokens instead.

Design notes
------------
- We don't store parsed FHIR in the DB — instead we re-run hl7_to_all() on
  the stored raw HL7.  This keeps the DB lean and the FHIR output always
  up-to-date with the latest transform logic.
- Patient IDs come from HL7 PID-3 (MRN).
- Encounter IDs are synthetic: "enc-{message_log_pk}".
- Bundles include a "total" count and "link" array (FHIR pagination hints).
"""

import uuid
from datetime import datetime, timezone

from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required

from .models import HL7MessageLog
from .hl7_utils import hl7_to_all, hl7_oru_to_fhir


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FHIR_CONTENT_TYPE = "application/fhir+json"


def fhir_response(data: dict, status: int = 200) -> JsonResponse:
    r = JsonResponse(data, status=status)
    r["Content-Type"] = FHIR_CONTENT_TYPE
    return r


def _issue(severity: str, code: str, details: str) -> dict:
    return {
        "resourceType": "OperationOutcome",
        "issue": [{"severity": severity, "code": code, "diagnostics": details}],
    }


def _bundle(resource_type: str, entries: list, total: int = None, request_url: str = "") -> dict:
    return {
        "resourceType": "Bundle",
        "id": uuid.uuid4().hex,
        "type": "searchset",
        "total": total if total is not None else len(entries),
        "link": [{"relation": "self", "url": request_url}],
        "entry": [{"resource": r, "search": {"mode": "match"}} for r in entries],
    }


def _log_to_patient(log: HL7MessageLog) -> dict | None:
    """Re-transform a stored HL7 log entry → FHIR Patient."""
    if not log.raw_hl7:
        return None
    result = hl7_to_all(log.raw_hl7)
    return result.get("patient")


def _log_to_encounter(log: HL7MessageLog) -> dict | None:
    """Re-transform a stored HL7 log entry → FHIR Encounter."""
    if not log.raw_hl7 or not log.encounter_present:
        return None
    result = hl7_to_all(log.raw_hl7)
    enc = result.get("encounter")
    if enc and isinstance(enc, dict):
        # Stable synthetic ID
        enc["id"] = f"enc-{log.pk}"
    return enc


def _log_to_report(log: HL7MessageLog) -> dict | None:
    """Re-transform an ORU log entry → FHIR DiagnosticReport."""
    if not log.raw_hl7 or not log.message_type.startswith("ORU"):
        return None
    result = hl7_oru_to_fhir(log.raw_hl7)
    return result.get("report")


# ---------------------------------------------------------------------------
# CapabilityStatement (metadata)
# ---------------------------------------------------------------------------

@require_GET
def fhir_metadata(request):
    """
    GET /fhir/
    Returns a minimal FHIR R4 CapabilityStatement describing this server.
    """
    statement = {
        "resourceType": "CapabilityStatement",
        "id": "django-sam-healthcare",
        "status": "active",
        "date": "2026-01-01",
        "kind": "instance",
        "fhirVersion": "4.0.1",
        "format": ["application/fhir+json"],
        "implementationGuide": [
            "http://hl7.org/fhir/us/core/ImplementationGuide/hl7.fhir.us.core"
        ],
        "software": {
            "name": "django-sam-healthcare",
            "version": "1.0.0",
        },
        "rest": [{
            "mode": "server",
            "security": {
                "cors": True,
                "service": [{
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/restful-security-service",
                        "code": "SMART-on-FHIR",
                    }]
                }],
                "description": "SMART on FHIR OAuth2 (demo: session auth used instead)",
            },
            "resource": [
                {
                    "type": "Patient",
                    "interaction": [
                        {"code": "read"},
                        {"code": "search-type"},
                    ],
                    "searchParam": [
                        {"name": "identifier", "type": "token"},
                        {"name": "family", "type": "string"},
                        {"name": "_id", "type": "token"},
                    ],
                },
                {
                    "type": "Encounter",
                    "interaction": [
                        {"code": "read"},
                        {"code": "search-type"},
                    ],
                    "searchParam": [
                        {"name": "subject", "type": "reference"},
                        {"name": "status", "type": "token"},
                    ],
                },
                {
                    "type": "DiagnosticReport",
                    "interaction": [
                        {"code": "read"},
                        {"code": "search-type"},
                    ],
                    "searchParam": [
                        {"name": "subject", "type": "reference"},
                        {"name": "category", "type": "token"},
                    ],
                },
            ],
            "operation": [
                {
                    "name": "export",
                    "definition": "http://hl7.org/fhir/uv/bulkdata/OperationDefinition/patient-export",
                    "documentation": (
                        "Bulk FHIR Patient export per FHIR Bulk Data IG v2.0. "
                        "Returns 202 Accepted + Content-Location for async polling. "
                        "Supports _since, _type, _outputFormat."
                    ),
                }
            ],
        }],
    }
    return fhir_response(statement)


# ---------------------------------------------------------------------------
# Patient
# ---------------------------------------------------------------------------

@login_required
@require_GET
def fhir_patient_search(request):
    """
    GET /fhir/Patient/
    Search params: identifier (MRN token), family (name string), _id

    Returns a FHIR Bundle of matching Patient resources.
    """
    qs = HL7MessageLog.objects.exclude(patient_id="").order_by("-created_at")

    identifier = request.GET.get("identifier", "").strip()
    family = request.GET.get("family", "").strip()
    _id = request.GET.get("_id", "").strip()

    if identifier:
        # Support both plain MRN and system|value token
        mrn = identifier.split("|")[-1]
        qs = qs.filter(patient_id=mrn)
    if family:
        qs = qs.filter(raw_hl7__icontains=family.upper())
    if _id:
        qs = qs.filter(patient_id=_id)

    # Deduplicate by patient_id — latest record per patient
    seen = {}
    for log in qs[:200]:
        if log.patient_id not in seen:
            seen[log.patient_id] = log

    patients = []
    for log in seen.values():
        p = _log_to_patient(log)
        if p:
            patients.append(p)

    return fhir_response(_bundle("Patient", patients, request_url=request.build_absolute_uri()))


@login_required
@require_GET
def fhir_patient_read(request, patient_id: str):
    """
    GET /fhir/Patient/<patient_id>/
    Returns the most recent FHIR Patient for this MRN.
    """
    log = (
        HL7MessageLog.objects
        .filter(patient_id=patient_id)
        .exclude(raw_hl7="")
        .order_by("-created_at")
        .first()
    )
    if not log:
        return fhir_response(_issue("error", "not-found", f"No patient found with id {patient_id}"), status=404)

    patient = _log_to_patient(log)
    if not patient:
        return fhir_response(_issue("error", "not-found", "Could not transform patient data"), status=404)

    patient.setdefault("id", patient_id)
    return fhir_response(patient)


# ---------------------------------------------------------------------------
# Encounter
# ---------------------------------------------------------------------------

@login_required
@require_GET
def fhir_encounter_search(request):
    """
    GET /fhir/Encounter/
    Search params: subject (Patient/MRN reference), status
    """
    qs = HL7MessageLog.objects.filter(encounter_present=True).order_by("-created_at")

    subject = request.GET.get("subject", "").strip()
    if subject:
        patient_id = subject.replace("Patient/", "")
        qs = qs.filter(patient_id=patient_id)

    encounters = []
    for log in qs[:50]:
        enc = _log_to_encounter(log)
        if enc:
            encounters.append(enc)

    return fhir_response(_bundle("Encounter", encounters, request_url=request.build_absolute_uri()))


@login_required
@require_GET
def fhir_encounter_read(request, encounter_id: str):
    """
    GET /fhir/Encounter/<encounter_id>/
    encounter_id format: enc-{message_log_pk}
    """
    try:
        pk = int(encounter_id.replace("enc-", ""))
    except ValueError:
        return fhir_response(_issue("error", "invalid", f"Invalid encounter id: {encounter_id}"), status=400)

    log = HL7MessageLog.objects.filter(pk=pk, encounter_present=True).first()
    if not log:
        return fhir_response(_issue("error", "not-found", f"Encounter {encounter_id} not found"), status=404)

    enc = _log_to_encounter(log)
    if not enc:
        return fhir_response(_issue("error", "not-found", "Could not transform encounter data"), status=404)

    return fhir_response(enc)


# ---------------------------------------------------------------------------
# DiagnosticReport (ORU)
# ---------------------------------------------------------------------------

@login_required
@require_GET
def fhir_report_search(request):
    """
    GET /fhir/DiagnosticReport/
    Search params: subject (Patient/MRN)
    """
    qs = HL7MessageLog.objects.filter(message_type__startswith="ORU").order_by("-created_at")

    subject = request.GET.get("subject", "").strip()
    if subject:
        patient_id = subject.replace("Patient/", "")
        qs = qs.filter(patient_id=patient_id)

    reports = []
    for log in qs[:50]:
        r = _log_to_report(log)
        if r:
            reports.append(r)

    return fhir_response(_bundle("DiagnosticReport", reports, request_url=request.build_absolute_uri()))
