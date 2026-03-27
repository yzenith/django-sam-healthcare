from django.contrib import admin
from .models import ADTMessage, DFTChargeItem, DFTMessage


@admin.register(ADTMessage)
class ADTMessageAdmin(admin.ModelAdmin):
    list_display    = ("id", "patient_id", "event_type", "status", "timestamp", "facility", "location")
    list_filter     = ("event_type", "status")
    search_fields   = ("patient_id", "note")
    ordering        = ("-timestamp",)
    readonly_fields = ("timestamp", "raw_hl7")


class DFTChargeItemInline(admin.TabularInline):
    model           = DFTChargeItem
    extra           = 0
    readonly_fields = (
        "line_number", "charge_id", "service_date", "transaction_type",
        "procedure_code", "procedure_description", "revenue_code",
        "department", "quantity", "unit_amount", "total_amount", "insurance_plan",
    )
    can_delete = False


@admin.register(DFTMessage)
class DFTMessageAdmin(admin.ModelAdmin):
    list_display    = (
        "id", "patient_id", "encounter_id", "claim_id",
        "trigger_event", "total_charges", "status", "timestamp",
    )
    list_filter     = ("trigger_event", "status")
    search_fields   = ("patient_id", "encounter_id", "claim_id")
    ordering        = ("-timestamp",)
    readonly_fields = ("timestamp", "raw_hl7", "x12_837", "adt_message")
    inlines         = [DFTChargeItemInline]
