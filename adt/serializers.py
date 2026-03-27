from rest_framework import serializers
from .models import ADTMessage


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
