from django.db import models


class ADTMessage(models.Model):
    """
    Stores each simulated HL7 v2 ADT message.

    One row per triggered ADT event. The raw_hl7 field holds the full
    HL7 v2.3 string so it can be inspected or replayed downstream.
    """

    class EventType(models.TextChoices):
        A01 = "A01", "A01 – Admit Patient"
        A02 = "A02", "A02 – Transfer Patient"
        A03 = "A03", "A03 – Discharge Patient"
        A08 = "A08", "A08 – Update Patient Info"

    class Status(models.TextChoices):
        GENERATED = "GENERATED", "Generated"
        SENT      = "SENT",      "Sent"
        FAILED    = "FAILED",    "Failed"

    patient_id = models.CharField(max_length=64, db_index=True)
    event_type = models.CharField(max_length=3, choices=EventType.choices, db_index=True)
    timestamp  = models.DateTimeField(auto_now_add=True, db_index=True)
    raw_hl7    = models.TextField()
    status     = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.GENERATED,
        db_index=True,
    )
    # Optional context fields populated at generation time
    facility   = models.CharField(max_length=64, blank=True, default="")
    location   = models.CharField(max_length=64, blank=True, default="")
    note       = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["event_type", "timestamp"]),
            models.Index(fields=["status", "timestamp"]),
            models.Index(fields=["patient_id", "timestamp"]),
        ]

    def __str__(self):
        return f"ADT^{self.event_type} pid={self.patient_id} [{self.status}]"
