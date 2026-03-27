from django.contrib import admin
from .models import SFTPIngestRun, ClinicalRecord


class ClinicalRecordInline(admin.TabularInline):
    model  = ClinicalRecord
    extra  = 0
    fields = ["mrn", "visit_date", "visit_type", "diagnosis_code", "procedure_code", "provider_id"]
    readonly_fields = fields


@admin.register(SFTPIngestRun)
class SFTPIngestRunAdmin(admin.ModelAdmin):
    list_display   = [
        "id", "filename", "status", "schema_type", "detected_delimiter",
        "total_rows", "valid_rows", "inserted", "updated", "rejected",
        "duplicates_in_file", "created_at",
    ]
    list_filter    = ["status", "schema_type", "detected_delimiter"]
    search_fields  = ["filename"]
    readonly_fields = [
        "created_at", "total_rows", "valid_rows", "inserted", "updated",
        "rejected", "duplicates_in_file", "validation_errors", "processing_summary",
    ]
    inlines = [ClinicalRecordInline]


@admin.register(ClinicalRecord)
class ClinicalRecordAdmin(admin.ModelAdmin):
    list_display  = ["id", "mrn", "visit_date", "diagnosis_code", "procedure_code", "ingest_run", "created_at"]
    list_filter   = ["visit_date"]
    search_fields = ["mrn", "diagnosis_code", "procedure_code"]
    readonly_fields = ["created_at", "ingest_run"]
