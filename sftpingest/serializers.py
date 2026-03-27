"""
sftpingest/serializers.py
~~~~~~~~~~~~~~~~~~~~~~~~~
DRF serializers for the SFTP flat-file ingestion REST API.
"""

from rest_framework import serializers
from .models import SFTPIngestRun, ClinicalRecord


class ClinicalRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ClinicalRecord
        fields = [
            "id", "mrn", "visit_date", "visit_type",
            "diagnosis_code", "procedure_code",
            "provider_id", "facility_code", "notes", "created_at",
        ]


class SFTPIngestRunSerializer(serializers.ModelSerializer):
    reject_rate   = serializers.FloatField(read_only=True)
    success_rate  = serializers.FloatField(read_only=True)

    class Meta:
        model  = SFTPIngestRun
        fields = [
            "id", "created_at", "filename", "status",
            "schema_type", "detected_delimiter",
            "total_rows", "valid_rows", "inserted", "updated",
            "rejected", "duplicates_in_file",
            "validation_errors", "processing_summary",
            "error_message", "reject_rate", "success_rate",
        ]


class SFTPIngestRunListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views — omits bulky JSON fields."""
    reject_rate  = serializers.FloatField(read_only=True)
    success_rate = serializers.FloatField(read_only=True)

    class Meta:
        model  = SFTPIngestRun
        fields = [
            "id", "created_at", "filename", "status",
            "schema_type", "detected_delimiter",
            "total_rows", "valid_rows", "inserted", "updated",
            "rejected", "duplicates_in_file",
            "reject_rate", "success_rate",
        ]
