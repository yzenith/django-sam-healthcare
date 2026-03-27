from django.contrib import admin
from .models import ADTMessage


@admin.register(ADTMessage)
class ADTMessageAdmin(admin.ModelAdmin):
    list_display  = ("id", "patient_id", "event_type", "status", "timestamp", "facility", "location")
    list_filter   = ("event_type", "status")
    search_fields = ("patient_id", "note")
    ordering      = ("-timestamp",)
    readonly_fields = ("timestamp", "raw_hl7")
