# example/admin.py
from django.contrib import admin
from .models import HL7MessageLog


@admin.register(HL7MessageLog)
class HL7MessageLogAdmin(admin.ModelAdmin):
    date_hierarchy = "created_at"
    list_display = ("created_at", "message_type", "patient_id", "source_system", "x12_length")
    list_filter = ("message_type", "source_system", "created_at")
    search_fields = ("patient_id", "raw_hl7")
    readonly_fields = ("created_at",)
    list_per_page = 50
