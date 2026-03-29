from django.contrib import admin
from .models import SIUMessage


@admin.register(SIUMessage)
class SIUMessageAdmin(admin.ModelAdmin):
    list_display   = [
        "id", "event_type", "patient_id", "appointment_id",
        "appointment_dt", "appointment_type", "provider_name",
        "location", "status", "timestamp",
    ]
    list_filter    = ["event_type", "status", "appointment_type"]
    search_fields  = ["patient_id", "appointment_id", "provider_id"]
    readonly_fields = ["timestamp", "raw_hl7"]
