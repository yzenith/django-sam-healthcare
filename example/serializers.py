# app/serializers.py
from rest_framework import serializers

class HL7TransformRequestSerializer(serializers.Serializer):
    hl7_message = serializers.CharField()
