from rest_framework import serializers
from .models import TraceLog, TraceStep


class TraceStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = TraceStep
        fields = ["sequence", "step_name", "status", "message", "details", "created_at"]


class TraceLogListSerializer(serializers.ModelSerializer):
    class Meta:
        model = TraceLog
        fields = ["trace_id", "timestamp", "input_type", "summary", "error_count", "output_type", "status", "duration_ms"]


class TraceLogDetailSerializer(serializers.ModelSerializer):
    steps = TraceStepSerializer(many=True)

    class Meta:
        model = TraceLog
        fields = [
            "trace_id", "timestamp", "input_type", "output_type", "status",
            "summary", "error_count", "duration_ms",
            "raw_payload", "parsed_preview", "meta",
            "steps",
        ]


class IngestSerializer(serializers.Serializer):
    input_type = serializers.ChoiceField(choices=["HL7", "JSON", "EDI", "OTHER"], required=False)
    output_type = serializers.CharField(required=False, default="FHIR_JSON")
    raw_payload = serializers.CharField()
    meta = serializers.JSONField(required=False)
