from django.db import models

class HL7MessageLog(models.Model):
    

    class ProcessingStatus(models.TextChoices):
        RECEIVED = "RECEIVED", "RECEIVED"
        VALIDATED = "VALIDATED", "VALIDATED"
        TRANSFORMED = "TRANSFORMED", "TRANSFORMED"
        FAILED = "FAILED", "FAILED"

    class ErrorCategory(models.TextChoices):
        NONE = "NONE", "NONE"
        VALIDATION = "VALIDATION", "VALIDATION"
        MAPPING = "MAPPING", "MAPPING"
        DOWNSTREAM = "DOWNSTREAM", "DOWNSTREAM"
        AUTH = "AUTH", "AUTH"
        SOURCE_SYSTEM = "SOURCE_SYSTEM", "SOURCE_SYSTEM"
        FACILITY_VARIANCE = "FACILITY_VARIANCE", "FACILITY_VARIANCE"
        UNKNOWN = "UNKNOWN", "UNKNOWN"
    
    # Add an index for the ordering/filter pattern:
    class Meta:
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["processing_status", "-created_at"]),
            models.Index(fields=["message_type", "-created_at"]),
        ]

    created_at = models.DateTimeField(auto_now_add=True)
    source_context = models.JSONField(default=dict, blank=True)
    source_system = models.CharField(max_length=50, blank=True)
    message_type = models.CharField(max_length=20, blank=True)
    message_profile = models.CharField(max_length=128, blank=True, default="")
    trigger_event = models.JSONField(default=dict, blank=True)

    raw_hl7 = models.TextField()
    patient_id = models.CharField(max_length=64, blank=True)
    encounter_present = models.BooleanField(default=False)
    x12_length = models.IntegerField(default=0)

    trace_id = models.CharField(max_length=32, unique=True, db_index=True, null=True, blank=True)
    processing_status = models.CharField(max_length=16, choices=ProcessingStatus.choices, default=ProcessingStatus.RECEIVED, db_index=True)
    error_category = models.CharField(max_length=32, choices=ErrorCategory.choices, default=ErrorCategory.NONE, db_index=True)
    error_message = models.TextField(blank=True, default="")
    steps = models.JSONField(default=list, blank=True)

    patient_class = models.CharField(max_length=8, blank=True)
    event_time = models.DateTimeField(null=True, blank=True)
    has_x12 = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.created_at} {self.message_type} {self.patient_id}"