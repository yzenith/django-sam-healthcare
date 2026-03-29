from rest_framework import serializers
from .models import CCDADocument


class CCDADocumentSerializer(serializers.ModelSerializer):
    patient_mrn = serializers.CharField(source="patient.mrn", read_only=True)

    class Meta:
        model  = CCDADocument
        fields = [
            "id", "document_id", "document_type", "patient_mrn",
            "created_at", "xml_content",
        ]


class CCDADocumentListSerializer(serializers.ModelSerializer):
    patient_mrn = serializers.CharField(source="patient.mrn", read_only=True)

    class Meta:
        model  = CCDADocument
        fields = ["id", "document_id", "document_type", "patient_mrn", "created_at"]
