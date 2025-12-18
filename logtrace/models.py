from django.db import models
from django.utils import timezone


class TraceLog(models.Model):
    class InputType(models.TextChoices):
        HL7 = "HL7", "HL7"
        JSON = "JSON", "JSON"
        EDI = "EDI", "EDI"
        OTHER = "OTHER", "OTHER"

    class Status(models.TextChoices):
        RECEIVED = "RECEIVED", "RECEIVED"
        PROCESSED = "PROCESSED", "PROCESSED"
        FAILED = "FAILED", "FAILED"

    trace_id = models.CharField(max_length=64, unique=True, db_index=True)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)

    input_type = models.CharField(max_length=16, choices=InputType.choices, default=InputType.OTHER)
    output_type = models.CharField(max_length=32, blank=True, default="")

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RECEIVED)
    summary = models.CharField(max_length=255, blank=True, default="")
    error_count = models.IntegerField(default=0)

    duration_ms = models.IntegerField(null=True, blank=True)

    raw_payload = models.TextField()
    parsed_preview = models.JSONField(null=True, blank=True)  # small structured preview, not full PHI
    meta = models.JSONField(default=dict, blank=True)         # headers, sender, route, etc.

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.trace_id} {self.input_type} {self.status}"


class TraceStep(models.Model):
    class StepStatus(models.TextChoices):
        OK = "OK", "OK"
        WARN = "WARN", "WARN"
        ERROR = "ERROR", "ERROR"

    trace_log = models.ForeignKey(TraceLog, related_name="steps", on_delete=models.CASCADE)
    sequence = models.IntegerField()

    step_name = models.CharField(max_length=64)      # parse / validate / transform / route / ack
    status = models.CharField(max_length=8, choices=StepStatus.choices, default=StepStatus.OK)

    message = models.CharField(max_length=255, blank=True, default="")
    details = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sequence"]
        index_together = [("trace_log", "sequence")]

    def __str__(self):
        return f"{self.trace_log.trace_id} #{self.sequence} {self.step_name} {self.status}"
