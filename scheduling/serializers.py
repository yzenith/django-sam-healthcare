from rest_framework import serializers
from .models import SIUMessage


class SIUTriggerSerializer(serializers.Serializer):
    patient_id       = serializers.CharField(max_length=64)
    event_type       = serializers.ChoiceField(choices=SIUMessage.EventType.choices)
    appointment_dt   = serializers.DateTimeField()
    duration_minutes = serializers.IntegerField(min_value=5, max_value=480, default=30)
    appointment_type = serializers.ChoiceField(
        choices=SIUMessage.AppointmentType.choices,
        default=SIUMessage.AppointmentType.ROUTINE,
    )
    provider_id      = serializers.CharField(max_length=64,  required=False, default="")
    provider_name    = serializers.CharField(max_length=128, required=False, default="")
    location         = serializers.CharField(max_length=64,  required=False, default="")
    reason           = serializers.CharField(max_length=128, required=False, default="")
    note             = serializers.CharField(max_length=255, required=False, default="")


class SIUMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model  = SIUMessage
        fields = "__all__"


class SIUMessageListSerializer(serializers.ModelSerializer):
    class Meta:
        model  = SIUMessage
        exclude = ["raw_hl7"]
