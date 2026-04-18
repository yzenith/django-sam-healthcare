import uuid
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
            models.Index(fields=["created_at"]),
            models.Index(fields=["processing_status", "created_at"]),
            models.Index(fields=["message_type", "created_at"]),
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


class ClaimRecord(models.Model):
    """
    Persists claim lifecycle data for billing reconciliation reporting.

    Created when an ADT message with X12 output is processed through
    MirthHL7View. Tracks the full claim lifecycle: submitted → payer
    response → reconciliation.

    In production this would link to an ERA (835) when received. Here
    the 835 is simulated at transform time so all three states are
    captured in one write.
    """

    class ClaimStatus(models.TextChoices):
        SUBMITTED  = "SUBMITTED",  "Submitted"
        PAID       = "PAID",       "Paid"
        PARTIAL    = "PARTIAL",    "Partial Payment"
        DENIED     = "DENIED",     "Denied"
        PENDING    = "PENDING",    "Pending"

    created_at      = models.DateTimeField(auto_now_add=True)
    message_log     = models.OneToOneField(
        HL7MessageLog,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="claim",
    )
    trace_id        = models.CharField(max_length=32, blank=True, default="", db_index=True)
    claim_id        = models.CharField(max_length=64, blank=True, default="", db_index=True)
    patient_id      = models.CharField(max_length=64, blank=True, default="")
    status          = models.CharField(
        max_length=16,
        choices=ClaimStatus.choices,
        default=ClaimStatus.SUBMITTED,
        db_index=True,
    )

    billed_amount          = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    paid_amount            = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    patient_responsibility = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    adjustment_amount      = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    balance_due            = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # Raw 837/835 for audit
    x12_837 = models.TextField(blank=True, default="")
    x12_835 = models.TextField(blank=True, default="")

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["patient_id", "created_at"]),
        ]

    def __str__(self):
        return f"Claim {self.claim_id} [{self.status}] billed={self.billed_amount} paid={self.paid_amount}"


class WebhookDelivery(models.Model):
    """
    Records every outbound FHIR webhook delivery attempt.

    After a successful HL7 transform, the pipeline sends the FHIR
    resource to a configured downstream URL (EHR, analytics platform,
    notification service). This model stores:
      - what was sent (fhir_resource_type, fhir_payload)
      - where it was sent (target_url)
      - whether it succeeded (status, response_code)
      - how long it took (duration_ms)

    In production this would use a task queue (Celery/SQS). Here we
    simulate synchronous delivery for demo purposes.
    """

    class DeliveryStatus(models.TextChoices):
        PENDING   = "PENDING",   "Pending"
        DELIVERED = "DELIVERED", "Delivered"
        FAILED    = "FAILED",    "Failed"
        RETRYING  = "RETRYING",  "Retrying"

    created_at         = models.DateTimeField(auto_now_add=True)
    delivered_at       = models.DateTimeField(null=True, blank=True)

    trace_id           = models.CharField(max_length=32, blank=True, default="", db_index=True)
    fhir_resource_type = models.CharField(max_length=64, blank=True, default="")
    fhir_payload       = models.JSONField(default=dict)
    target_url         = models.CharField(max_length=255, blank=True, default="")

    status             = models.CharField(
        max_length=16,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.PENDING,
        db_index=True,
    )
    response_code      = models.IntegerField(null=True, blank=True)
    response_body      = models.TextField(blank=True, default="")
    duration_ms        = models.IntegerField(null=True, blank=True)
    attempt_count      = models.IntegerField(default=1)
    error_detail       = models.TextField(blank=True, default="")
    next_retry_at      = models.DateTimeField(null=True, blank=True)
    max_retries        = models.IntegerField(default=3)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["trace_id"]),
        ]

    def __str__(self):
        return f"Webhook {self.fhir_resource_type} [{self.status}] trace={self.trace_id}"


# ---------------------------------------------------------------------------
# SMART on FHIR OAuth2
# ---------------------------------------------------------------------------

class OAuthClient(models.Model):
    client_id = models.CharField(max_length=100, unique=True, default=uuid.uuid4)
    client_secret_hash = models.CharField(max_length=255, blank=True)
    client_name = models.CharField(max_length=200)
    redirect_uris = models.JSONField(default=list)
    scopes_allowed = models.JSONField(default=list)
    grant_types = models.JSONField(default=list)
    is_public = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.client_name} ({self.client_id})"


class OAuthAuthCode(models.Model):
    code = models.CharField(max_length=128, unique=True)
    client = models.ForeignKey(OAuthClient, on_delete=models.CASCADE)
    user = models.ForeignKey("auth.User", on_delete=models.CASCADE, null=True, blank=True)
    redirect_uri = models.TextField()
    scopes = models.JSONField(default=list)
    patient_context = models.CharField(max_length=100, blank=True)
    code_challenge = models.CharField(max_length=255, blank=True)
    code_challenge_method = models.CharField(max_length=10, blank=True, default="S256")
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"AuthCode {self.code[:12]}… client={self.client.client_name}"


class OAuthToken(models.Model):
    access_token = models.TextField(unique=True)
    client = models.ForeignKey(OAuthClient, on_delete=models.CASCADE)
    user = models.ForeignKey("auth.User", on_delete=models.CASCADE, null=True, blank=True)
    scopes = models.JSONField(default=list)
    patient_context = models.CharField(max_length=100, blank=True)
    expires_at = models.DateTimeField()
    refresh_token = models.CharField(max_length=255, blank=True, db_index=True)
    refresh_expires_at = models.DateTimeField(null=True, blank=True)
    revoked = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["revoked", "expires_at"])]

    def __str__(self):
        return f"Token client={self.client.client_name} revoked={self.revoked}"


# ---------------------------------------------------------------------------
# Bulk FHIR Export
# ---------------------------------------------------------------------------

class BulkExportJob(models.Model):
    class Status(models.TextChoices):
        PENDING  = "pending",  "Pending"
        RUNNING  = "running",  "Running"
        COMPLETE = "complete", "Complete"
        ERROR    = "error",    "Error"

    job_id        = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    resource_type = models.CharField(max_length=100, default="Patient")
    status        = models.CharField(max_length=20, choices=Status.choices, default=Status.COMPLETE)
    output_files  = models.JSONField(default=list)
    ndjson_data   = models.JSONField(default=dict)
    error         = models.TextField(blank=True)
    since         = models.DateTimeField(null=True, blank=True)
    requested_by  = models.CharField(max_length=100, blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)
    completed_at  = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"BulkExport {self.job_id} [{self.status}] {self.resource_type}"