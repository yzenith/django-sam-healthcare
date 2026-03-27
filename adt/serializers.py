from rest_framework import serializers
from .models import ADTMessage, DFTMessage, DFTChargeItem


class ADTTriggerSerializer(serializers.Serializer):
    patient_id = serializers.CharField(max_length=64)
    event_type = serializers.ChoiceField(choices=ADTMessage.EventType.choices)
    note       = serializers.CharField(max_length=255, required=False, default="")


class ADTMessageSerializer(serializers.ModelSerializer):
    event_type_display = serializers.CharField(source="get_event_type_display", read_only=True)
    status_display     = serializers.CharField(source="get_status_display",     read_only=True)

    class Meta:
        model  = ADTMessage
        fields = [
            "id", "patient_id", "event_type", "event_type_display",
            "timestamp", "status", "status_display",
            "facility", "location", "note", "raw_hl7",
        ]
        read_only_fields = fields


class DFTChargeItemSerializer(serializers.ModelSerializer):
    transaction_type_display = serializers.CharField(
        source="get_transaction_type_display", read_only=True
    )

    class Meta:
        model  = DFTChargeItem
        fields = [
            "line_number", "charge_id", "encounter_batch",
            "service_date", "transaction_type", "transaction_type_display",
            "procedure_code", "procedure_description", "revenue_code",
            "department", "insurance_plan",
            "unit_amount", "quantity", "total_amount",
        ]
        read_only_fields = fields


class DFTMessageSerializer(serializers.ModelSerializer):
    status_display        = serializers.CharField(source="get_status_display",        read_only=True)
    trigger_event_display = serializers.CharField(source="get_trigger_event_display", read_only=True)
    charges               = DFTChargeItemSerializer(many=True, read_only=True)
    adt_message_id        = serializers.PrimaryKeyRelatedField(
        source="adt_message", read_only=True
    )

    class Meta:
        model  = DFTMessage
        fields = [
            "id", "patient_id", "encounter_id", "claim_id",
            "trigger_event", "trigger_event_display",
            "timestamp", "status", "status_display",
            "total_charges", "adt_message_id",
            "charges", "raw_hl7", "x12_837",
        ]
        read_only_fields = fields


class DFTMessageListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views — omits raw_hl7 and x12_837."""
    status_display        = serializers.CharField(source="get_status_display",        read_only=True)
    trigger_event_display = serializers.CharField(source="get_trigger_event_display", read_only=True)
    charge_count          = serializers.IntegerField(source="charges.count",          read_only=True)
    adt_message_id        = serializers.PrimaryKeyRelatedField(
        source="adt_message", read_only=True
    )

    class Meta:
        model  = DFTMessage
        fields = [
            "id", "patient_id", "encounter_id", "claim_id",
            "trigger_event", "trigger_event_display",
            "timestamp", "status", "status_display",
            "total_charges", "charge_count", "adt_message_id",
        ]
        read_only_fields = fields
