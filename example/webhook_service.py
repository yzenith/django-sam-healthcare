"""
example/webhook_service.py

Outbound FHIR webhook delivery service.

KEY DESIGN PATTERN: Separation of concerns
  - The view (MirthHL7View) decides *what* to send
  - This service decides *how* to deliver it and *records the outcome*
  - The model (WebhookDelivery) is the audit trail

In production:
  - `deliver_fhir_webhook` would be a Celery task or SQS consumer
  - The target URL would come from a per-facility configuration table
  - Retries would use exponential backoff
  - Failures would trigger ops alerts

For this demo:
  - We simulate HTTP delivery (no real outbound request)
  - We alternate success/failure to show both states in the UI
  - Duration is realistic (20-150ms range)
"""

import json
import time
import random
from django.utils import timezone

from .models import WebhookDelivery

# Simulated downstream endpoints — in production these come from config
SIMULATED_TARGETS = {
    "Patient":            "https://ehr.example.com/fhir/Patient",
    "Encounter":          "https://ehr.example.com/fhir/Encounter",
    "Appointment":        "https://scheduling.example.com/fhir/Appointment",
    "ServiceRequest":     "https://orders.example.com/fhir/ServiceRequest",
    "DocumentReference":  "https://cdms.example.com/fhir/DocumentReference",
    "DiagnosticReport":   "https://lab.example.com/fhir/DiagnosticReport",
}

DEFAULT_TARGET = "https://downstream.example.com/fhir"

# Simulated failure reasons — realistic payer/downstream errors
SIMULATED_ERRORS = [
    "Connection timeout after 5000ms",
    "Downstream returned 503 Service Unavailable",
    "TLS handshake failed: certificate expired",
    "Downstream returned 422 Unprocessable Entity: missing required field 'subject'",
]


def deliver_fhir_webhook(
    fhir_payload: dict,
    fhir_resource_type: str,
    trace_id: str,
    force_outcome: str = None,   # "success" or "failure" — for tests
) -> WebhookDelivery:
    """
    Simulate delivering a FHIR resource to a downstream system.

    Creates a WebhookDelivery record with the outcome. In a real system
    this would make an HTTP POST and record the actual response.

    Args:
        fhir_payload: The FHIR resource dict to deliver
        fhir_resource_type: e.g. "Patient", "Appointment"
        trace_id: Links delivery back to the originating HL7 message
        force_outcome: Override random outcome (used in tests)

    Returns:
        The saved WebhookDelivery instance
    """
    target_url = SIMULATED_TARGETS.get(fhir_resource_type, DEFAULT_TARGET)

    delivery = WebhookDelivery.objects.create(
        trace_id=trace_id,
        fhir_resource_type=fhir_resource_type,
        fhir_payload=fhir_payload,
        target_url=target_url,
        status=WebhookDelivery.DeliveryStatus.PENDING,
    )

    # Simulate network latency
    start = time.time()
    time.sleep(random.uniform(0.01, 0.05))   # 10-50ms simulated latency

    # Determine outcome: 80% success in demo (realistic for a healthy endpoint)
    if force_outcome == "success":
        success = True
    elif force_outcome == "failure":
        success = False
    else:
        success = random.random() < 0.80

    duration_ms = int((time.time() - start) * 1000)

    if success:
        delivery.status       = WebhookDelivery.DeliveryStatus.DELIVERED
        delivery.response_code = 201
        delivery.response_body = json.dumps({
            "resourceType": fhir_resource_type,
            "id": f"downstream-{delivery.id}",
            "meta": {"source": "django-sam-healthcare"},
        })
        delivery.delivered_at  = timezone.now()
    else:
        error = random.choice(SIMULATED_ERRORS)
        delivery.status        = WebhookDelivery.DeliveryStatus.FAILED
        delivery.response_code = 503
        delivery.response_body = ""
        delivery.error_detail  = error

    delivery.duration_ms = duration_ms
    delivery.save(update_fields=[
        "status", "response_code", "response_body",
        "delivered_at", "duration_ms", "error_detail",
    ])

    return delivery


def dispatch_webhooks_for_result(result: dict, trace_id: str) -> list[WebhookDelivery]:
    """
    Given a transform result dict from hl7_to_all(), dispatch webhooks
    for every FHIR resource present in the result.

    This is the integration point called from MirthHL7View after a
    successful transform.

    Returns list of WebhookDelivery instances created.
    """
    deliveries = []

    # Map result keys to FHIR resource types
    resource_map = {
        "patient":            "Patient",
        "encounter":          "Encounter",
        "appointment":        "Appointment",
        "service_request":    "ServiceRequest",
        "document_reference": "DocumentReference",
        "report":             "DiagnosticReport",
    }

    for key, resource_type in resource_map.items():
        payload = result.get(key)
        if payload and isinstance(payload, dict):
            delivery = deliver_fhir_webhook(
                fhir_payload=payload,
                fhir_resource_type=resource_type,
                trace_id=trace_id,
            )
            deliveries.append(delivery)

    return deliveries
