# example/urls.py
from django.views.generic import TemplateView
from django.urls import path

from example.views import (
    hl7_playground, HL7TransformView, MirthHL7View,
    mirth_message_detail, mirth_messages, home,
    patient_import_detail, patient_import_page, patient_import_rejects_csv,
    health, claim_reconciliation_report, webhook_delivery_log,
    seed_demo_data_view, retry_webhook, integration_specs,
)
from example.fhir_views import (
    fhir_metadata,
    fhir_patient_search, fhir_patient_read,
    fhir_encounter_search, fhir_encounter_read,
    fhir_report_search,
)
from example.smart_views import (
    smart_configuration,
    prior_auth_page, smart_on_fhir_page,
    CRDHookView, PASSubmitView,
)

urlpatterns = [
    # ── Home & health ────────────────────────────────────────────────────────
    path("", home, name="home"),
    path("health/", health, name="health"),

    # ── HL7 playground & transform ───────────────────────────────────────────
    path("api/transform/", HL7TransformView.as_view(), name="hl7-transform"),
    path("hl7/playground/", hl7_playground, name="hl7-playground"),

    # ── Mirth feed ───────────────────────────────────────────────────────────
    path("api/mirth/hl7/", MirthHL7View.as_view(), name="mirth-hl7"),
    path("mirth/messages/", mirth_messages, name="mirth-messages"),
    path("mirth/messages/<int:pk>/", mirth_message_detail, name="mirth-message-detail"),
    path("mirth/claims/reconciliation/", claim_reconciliation_report, name="claim-reconciliation"),

    # ── Webhooks ─────────────────────────────────────────────────────────────
    path("webhooks/", webhook_delivery_log, name="webhook-log"),
    path("webhooks/<int:pk>/retry/", retry_webhook, name="webhook-retry"),

    # ── Patient CSV import ───────────────────────────────────────────────────
    path("import/patients/", patient_import_page, name="patient-import"),
    path("import/patients/<int:pk>/", patient_import_detail, name="patient-import-detail"),
    path("import/patients/<int:pk>/rejects.csv", patient_import_rejects_csv, name="patient-import-rejects-csv"),

    # ── Seed demo data ───────────────────────────────────────────────────────
    path("seed-demo-data/", seed_demo_data_view, name="seed-demo-data"),

    # ── FHIR R4 API explorer page ────────────────────────────────────────────
    path("fhir-explorer/", TemplateView.as_view(template_name="fhir_api.html"), name="fhir-explorer"),

    # ── FHIR R4 REST API ─────────────────────────────────────────────────────
    path("fhir/",                              fhir_metadata,          name="fhir-metadata"),
    path("fhir/Patient/",                      fhir_patient_search,    name="fhir-patient-search"),
    path("fhir/Patient/<str:patient_id>/",     fhir_patient_read,      name="fhir-patient-read"),
    path("fhir/Encounter/",                    fhir_encounter_search,  name="fhir-encounter-search"),
    path("fhir/Encounter/<str:encounter_id>/", fhir_encounter_read,    name="fhir-encounter-read"),
    path("fhir/DiagnosticReport/",             fhir_report_search,     name="fhir-report-search"),

    # ── SMART on FHIR ────────────────────────────────────────────────────────
    path(".well-known/smart-configuration",    smart_configuration,    name="smart-configuration"),
    path("smart-on-fhir/",                     smart_on_fhir_page,     name="smart-on-fhir"),

    # ── Da Vinci Prior Auth ──────────────────────────────────────────────────
    path("api/prior-auth/crd/",  CRDHookView.as_view(),  name="prior-auth-crd"),
    path("api/prior-auth/pas/",  PASSubmitView.as_view(), name="prior-auth-pas"),
    path("prior-auth/",          prior_auth_page,         name="prior-auth"),

    # ── Static pages ─────────────────────────────────────────────────────────
    path("overview/", TemplateView.as_view(template_name="overview.html"), name="overview"),
    path("integrations/", integration_specs, name="integration-specs"),
    path("error-catalog/", TemplateView.as_view(template_name="error_catalog.html"), name="error-catalog"),
    path("case-studies/", TemplateView.as_view(template_name="case_studies/index.html"), name="case-studies-index"),
    path("case-studies/incident-001/",
         TemplateView.as_view(
             template_name="case_studies/incident_001.html",
             extra_context={
                 "incident_id": "INC-001",
                 "title": "HL7 Ingestion Success but Encounter Missing (Traceability Case Study)",
                 "severity": "S2",
                 "tags": ["HL7", "Mapping", "Traceability", "Reconciliation"],
                 "status": "Resolved (demo scenario)",
             },
         ),
         name="case-study-incident-001"),
    path("case-studies/incident-002/", TemplateView.as_view(template_name="case_studies/incident_002.html"), name="case-study-incident-002"),
]
