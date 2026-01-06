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


    # --- Analyst-facing computed fields (UI) ---

    @property
    def message_type(self) -> str:
        # HL7 message type is already in parsed_preview for HL7 (e.g., ADT^A01)
        if isinstance(self.parsed_preview, dict):
            mt = self.parsed_preview.get("message_type")
            if mt:
                return mt
        # fallback: allow meta override
        return (self.meta or {}).get("message_type", "") or "-"

    @property
    def source_system(self) -> str:
        m = self.meta or {}
        return m.get("source_system") or m.get("source") or "-"

    @property
    def trace_available(self) -> bool:
        # steps is related_name="steps"
        return self.steps.exists()

    @property
    def review_required(self) -> bool:
        # Analyst-friendly rule: any warnings/errors or failed processing
        if self.status == self.Status.FAILED:
            return True
        if self.error_count and self.error_count > 0:
            return True
        return self.steps.filter(status__in=["WARN", "ERROR"]).exists()

    @property
    def processing_status(self) -> str:
        """
        Analyst-facing status (different from internal TraceLog.status):
        SUCCESS / SUCCESS_WITH_WARNINGS / REJECTED / FAILED_TRANSFORMATION
        """
        if self.status == self.Status.FAILED:
            # in your pipeline, FAILED currently means validate/parsing issues caused transform skip
            return "FAILED_TRANSFORMATION"
        # processed but has WARN steps
        if self.steps.filter(status="WARN").exists():
            return "SUCCESS_WITH_WARNINGS"
        return "SUCCESS"

    @property
    def business_impact(self) -> str:
        """
        Keep it simple + deterministic.
        Allow override via meta['business_impact'].
        """
        m = self.meta or {}
        if m.get("business_impact") in {"Low", "Medium", "High"}:
            return m["business_impact"]

        mt = (self.message_type or "").upper()
        # very conservative defaults
        if mt.startswith("ADT") and self.review_required:
            return "High"
        if self.review_required:
            return "Medium"
        return "Low"

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
        indexes = [
            models.Index(fields=["trace_log", "sequence"], name="tracestep_trace_seq_idx"),
        ]

    def __str__(self):
        return f"{self.trace_log.trace_id} #{self.sequence} {self.step_name} {self.status}"
