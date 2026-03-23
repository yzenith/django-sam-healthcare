"""
example/smart_views.py

SMART on FHIR + Da Vinci Prior Authorization simulation.

SMART on FHIR
-------------
SMART (Substitutable Medical Applications, Reusable Technologies) is the
OAuth2 authorization layer for FHIR APIs. Every ONC-certified EHR must
expose a /.well-known/smart-configuration endpoint describing its OAuth2
server so third-party apps can authenticate.

The authorization flow:
  1. App discovers SMART config at /.well-known/smart-configuration
  2. App redirects user to authorization_endpoint with requested scopes
     (e.g. patient/Patient.read launch/patient)
  3. EHR authenticates user, shows consent screen
  4. EHR redirects back with auth code
  5. App exchanges code for access_token + patient context
  6. App calls FHIR API with Bearer token

Da Vinci Prior Authorization
-----------------------------
CMS-0057-F (2026) requires payers to support FHIR-based prior auth workflows
using the Da Vinci Implementation Guides:

  CRD  (Coverage Requirements Discovery)
       Provider queries payer: "does this service need prior auth?"
       Response: YES/NO + required documentation list

  PAS  (Prior Authorization Support)
       Provider submits prior auth request as FHIR Bundle (Claim resource)
       Payer responds: approved / pended / denied

  DTR  (Documentation Templates and Rules)
       Payer-specified questionnaire auto-populates from patient EHR data
       Provider completes and attaches to PAS submission

This file provides:
  - GET  /.well-known/smart-configuration   SMART metadata endpoint
  - POST /api/prior-auth/crd/               CRD hook simulation
  - POST /api/prior-auth/pas/               PAS submission simulation
  - GET  /prior-auth/                       Human-readable explainer page
"""

import uuid
import random
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status as drf_status
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers


# ---------------------------------------------------------------------------
# SMART on FHIR /.well-known/smart-configuration
# ---------------------------------------------------------------------------

BASE_FHIR_URL = "https://django-sam-healthcare.vercel.app/fhir"

@require_GET
def smart_configuration(request):
    """
    GET /.well-known/smart-configuration

    Returns the SMART on FHIR authorization server metadata.
    Third-party apps discover this endpoint to initiate the OAuth2 flow.

    In production these would point to a real OAuth2 server (Keycloak,
    Azure AD B2C, AWS Cognito, etc.). Here we return realistic mock URLs.
    """
    base = request.build_absolute_uri("/")
    config = {
        "issuer": base.rstrip("/"),
        "jwks_uri": f"{base}.well-known/jwks.json",
        "authorization_endpoint": f"{base}oauth2/authorize",
        "token_endpoint": f"{base}oauth2/token",
        "token_endpoint_auth_methods_supported": [
            "client_secret_basic",
            "private_key_jwt",
        ],
        "grant_types_supported": [
            "authorization_code",
            "client_credentials",
        ],
        "registration_endpoint": f"{base}oauth2/register",
        "scopes_supported": [
            "openid",
            "profile",
            "launch",
            "launch/patient",
            "patient/*.read",
            "patient/Patient.read",
            "patient/Encounter.read",
            "patient/DiagnosticReport.read",
            "patient/Observation.read",
            "user/*.read",
            "system/*.read",
            "offline_access",
        ],
        "response_types_supported": ["code"],
        "management_endpoint": f"{base}oauth2/manage",
        "introspection_endpoint": f"{base}oauth2/introspect",
        "revocation_endpoint": f"{base}oauth2/revoke",
        "code_challenge_methods_supported": ["S256"],
        "capabilities": [
            "launch-ehr",
            "launch-standalone",
            "client-public",
            "client-confidential-symmetric",
            "client-confidential-asymmetric",
            "sso-openid-connect",
            "context-banner",
            "context-style",
            "context-ehr-patient",
            "context-ehr-encounter",
            "permission-offline",
            "permission-patient",
            "permission-user",
            "permission-v2",
        ],
    }
    r = JsonResponse(config)
    r["Access-Control-Allow-Origin"] = "*"
    return r


# ---------------------------------------------------------------------------
# Da Vinci CRD — Coverage Requirements Discovery
# ---------------------------------------------------------------------------

# Simulated payer coverage rules
COVERAGE_RULES = {
    # service code → {requires_auth, documentation_needed}
    "99213": {"requires_pa": False, "reason": "Office visit — no prior auth required"},
    "73721": {"requires_pa": True,  "reason": "MRI joint — prior auth required by most plans"},
    "27447": {"requires_pa": True,  "reason": "Total knee replacement — prior auth required"},
    "93306": {"requires_pa": True,  "reason": "Echocardiography — prior auth required"},
    "70553": {"requires_pa": True,  "reason": "MRI brain with contrast — prior auth required"},
    "90837": {"requires_pa": False, "reason": "Psychotherapy — not subject to prior auth (mental health parity)"},
}

DOCUMENTATION_TEMPLATES = {
    "73721": ["Clinical notes (last 90 days)", "X-ray or prior imaging report", "Conservative treatment records"],
    "27447": ["Orthopedic consult note", "Conservative treatment failure documentation", "Functional assessment"],
    "93306": ["Cardiology referral", "Symptoms documentation", "Prior ECG results"],
    "70553": ["Neurology referral", "Symptom onset documentation", "Prior CT if available"],
}


class CRDHookView(APIView):
    """
    POST /api/prior-auth/crd/

    Simulates a CDS Hooks 'order-select' hook for Coverage Requirements
    Discovery. The EHR calls this when a provider selects a service/order
    to check if prior authorization is needed before the order is signed.

    Request body (CDS Hooks format):
      {
        "hook": "order-select",
        "hookInstance": "<uuid>",
        "context": {
          "patientId": "10001",
          "encounterId": "enc-42",
          "draftOrders": {
            "resourceType": "Bundle",
            "entry": [{"resource": {"resourceType": "ServiceRequest",
                                    "code": {"coding": [{"code": "73721"}]}}}]
          }
        }
      }

    Response: CDS Hooks cards array
    """
    @extend_schema(
        summary="CRD: Coverage Requirements Discovery hook",
        tags=["Da Vinci Prior Auth"],
        request=inline_serializer("CRDRequest", fields={
            "hook": drf_serializers.CharField(),
            "context": drf_serializers.DictField(),
        }),
        responses={200: inline_serializer("CRDResponse", fields={
            "cards": drf_serializers.ListField(child=drf_serializers.DictField()),
        })},
    )
    def post(self, request):
        data = request.data or {}
        context = data.get("context", {})

        # Extract service code from draftOrders Bundle
        service_code = None
        draft_orders = context.get("draftOrders", {})
        for entry in draft_orders.get("entry", []):
            resource = entry.get("resource", {})
            codings = resource.get("code", {}).get("coding", [])
            for c in codings:
                service_code = c.get("code")
                break
            if service_code:
                break

        # Fall back to direct service_code field (simplified callers)
        if not service_code:
            service_code = data.get("service_code", "99213")

        rule = COVERAGE_RULES.get(service_code, {
            "requires_pa": False,
            "reason": f"Service {service_code}: no coverage rule on file — check payer portal",
        })

        cards = []

        if rule["requires_pa"]:
            docs = DOCUMENTATION_TEMPLATES.get(service_code, ["Clinical documentation"])
            cards.append({
                "uuid": uuid.uuid4().hex,
                "summary": f"Prior Authorization Required — {service_code}",
                "detail": rule["reason"],
                "indicator": "warning",
                "source": {"label": "Demo Payer CRD Service", "url": "https://payer.example.com/crd"},
                "suggestions": [{
                    "label": "Submit Prior Auth via PAS",
                    "actions": [{
                        "type": "create",
                        "description": "Create PAS prior auth request",
                        "resource": {
                            "resourceType": "Task",
                            "status": "requested",
                            "intent": "proposal",
                            "code": {"coding": [{"code": "prior-auth"}]},
                        },
                    }],
                }],
                "links": [{
                    "label": "Submit via Da Vinci PAS",
                    "url": request.build_absolute_uri("/api/prior-auth/pas/"),
                    "type": "smart",
                }],
                "extension": {
                    "davinci-crd.coverage-information": {
                        "coverage-assertion": "auth-required",
                        "documentation-needed": docs,
                    }
                },
            })
        else:
            cards.append({
                "uuid": uuid.uuid4().hex,
                "summary": f"No Prior Authorization Required — {service_code}",
                "detail": rule["reason"],
                "indicator": "info",
                "source": {"label": "Demo Payer CRD Service"},
            })

        return Response({"cards": cards})


# ---------------------------------------------------------------------------
# Da Vinci PAS — Prior Authorization Support
# ---------------------------------------------------------------------------

class PASSubmitView(APIView):
    """
    POST /api/prior-auth/pas/

    Simulates a Da Vinci PAS prior authorization submission.
    The provider sends a FHIR Bundle containing a Claim resource.
    The payer responds synchronously with approved / pended / denied.

    Request body (simplified):
      {
        "patient_id": "10001",
        "service_code": "73721",
        "diagnosis_code": "M17.11",
        "ordering_provider": "2001^SMITH^ROBERT",
        "clinical_notes": "Patient has severe osteoarthritis..."
      }
    """
    @extend_schema(
        summary="PAS: Submit Prior Authorization Request",
        tags=["Da Vinci Prior Auth"],
        request=inline_serializer("PASRequest", fields={
            "patient_id": drf_serializers.CharField(),
            "service_code": drf_serializers.CharField(),
            "diagnosis_code": drf_serializers.CharField(required=False),
            "clinical_notes": drf_serializers.CharField(required=False),
        }),
        responses={200: inline_serializer("PASResponse", fields={
            "prior_auth_number": drf_serializers.CharField(),
            "decision": drf_serializers.CharField(),
            "decision_reason": drf_serializers.CharField(),
            "valid_from": drf_serializers.CharField(),
            "valid_to": drf_serializers.CharField(),
            "response_bundle": drf_serializers.DictField(),
        })},
    )
    def post(self, request):
        data = request.data or {}
        patient_id = data.get("patient_id", "UNKNOWN")
        service_code = data.get("service_code", "73721")
        diagnosis_code = data.get("diagnosis_code", "M17.11")
        has_notes = bool(data.get("clinical_notes", "").strip())

        # Simulate payer decision logic
        rule = COVERAGE_RULES.get(service_code, {"requires_pa": True})
        if not rule.get("requires_pa"):
            decision = "not-required"
            reason = "Service does not require prior authorization"
            pa_number = None
        elif not has_notes:
            decision = "pended"
            reason = "Clinical documentation incomplete — additional information required"
            pa_number = None
        elif service_code in ("27447",) and "osteoarthritis" not in data.get("clinical_notes", "").lower():
            decision = "denied"
            reason = "Medical necessity criteria not met — conservative treatment failure not documented"
            pa_number = None
        else:
            decision = "approved"
            reason = "Medical necessity criteria met"
            pa_number = f"PA-{uuid.uuid4().hex[:8].upper()}"

        from django.utils import timezone
        import datetime
        now = timezone.now()
        valid_from = now.date().isoformat()
        valid_to = (now + datetime.timedelta(days=90)).date().isoformat()

        response_bundle = {
            "resourceType": "Bundle",
            "id": uuid.uuid4().hex,
            "type": "collection",
            "entry": [{
                "resource": {
                    "resourceType": "ClaimResponse",
                    "id": uuid.uuid4().hex,
                    "status": "active",
                    "use": "preauthorization",
                    "patient": {"reference": f"Patient/{patient_id}"},
                    "outcome": decision,
                    "disposition": reason,
                    "preAuthRef": pa_number,
                    "preAuthPeriod": {"start": valid_from, "end": valid_to} if pa_number else None,
                    "item": [{
                        "itemSequence": 1,
                        "adjudication": [{
                            "category": {
                                "coding": [{"code": "submitted"}]
                            },
                            "amount": {"value": 0, "currency": "USD"},
                        }],
                    }],
                }
            }],
        }

        return Response({
            "prior_auth_number": pa_number,
            "decision": decision,
            "decision_reason": reason,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "response_bundle": response_bundle,
        })


# ---------------------------------------------------------------------------
# Prior Auth explainer page
# ---------------------------------------------------------------------------

@login_required
def prior_auth_page(request):
    """
    GET /prior-auth/
    Human-readable Da Vinci CRD / PAS / DTR explainer with live demo.
    """
    return render(request, "prior_auth.html")


# ---------------------------------------------------------------------------
# SMART on FHIR explainer page
# ---------------------------------------------------------------------------

@login_required
def smart_on_fhir_page(request):
    """
    GET /smart-on-fhir/
    Human-readable SMART on FHIR explainer.
    """
    return render(request, "smart_on_fhir.html")
