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
    
class PatientRecord(models.Model):
    mrn = models.CharField(max_length=64, unique=True, db_index=True)

    first_name = models.CharField(max_length=80, blank=True, default="")
    last_name = models.CharField(max_length=80, blank=True, default="")
    dob = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=16, blank=True, default="")

    address1 = models.CharField(max_length=120, blank=True, default="")
    city = models.CharField(max_length=80, blank=True, default="")
    state = models.CharField(max_length=2, blank=True, default="")
    zip_code = models.CharField(max_length=12, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.mrn} {self.last_name}, {self.first_name}"


class PatientImportRun(models.Model):
    class Status(models.TextChoices):
        RECEIVED = "RECEIVED", "RECEIVED"
        COMPLETED = "COMPLETED", "COMPLETED"
        FAILED = "FAILED", "FAILED"

    created_at = models.DateTimeField(auto_now_add=True)
    filename = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RECEIVED)

    total_rows = models.IntegerField(default=0)
    inserted = models.IntegerField(default=0)
    updated = models.IntegerField(default=0)
    rejected = models.IntegerField(default=0)
    duplicates_in_file = models.IntegerField(default=0)

    # Store a small sample for demo (avoid huge payloads)
    reject_samples = models.JSONField(default=list, blank=True)  # list of {"rownum":..,"reason":..,"row":..}
    reconciliation = models.JSONField(default=dict, blank=True)  # summary payload

    error_message = models.TextField(blank=True, default="")

    def __str__(self):
        return f"PatientImportRun {self.id} {self.status} {self.created_at}"