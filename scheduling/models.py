import uuid
from django.db import models


class SIUMessage(models.Model):
    """
    HL7 v2 SIU (Scheduling Information Unsolicited) message.

    SIU messages carry appointment events from a scheduling system to downstream
    consumers (EHR, patient portal, billing). Three trigger events are supported:

      S12 – New appointment booked
      S14 – Appointment modified (reschedule, location change, etc.)
      S15 – Appointment cancelled

    Segments generated: MSH · SCH · PID · PV1 · RGS · AIS · AIL · AIP
    """

    class EventType(models.TextChoices):
        S12 = "S12", "S12 – New Appointment"
        S14 = "S14", "S14 – Appointment Modified"
        S15 = "S15", "S15 – Appointment Cancelled"

    class Status(models.TextChoices):
        GENERATED = "GENERATED", "Generated"
        SENT      = "SENT",      "Sent"
        FAILED    = "FAILED",    "Failed"

    class AppointmentType(models.TextChoices):
        ROUTINE     = "ROUTINE",     "Routine"
        URGENT      = "URGENT",      "Urgent"
        WALK_IN     = "WALK_IN",     "Walk-In"
        FOLLOW_UP   = "FOLLOW_UP",   "Follow-Up"
        TELEHEALTH  = "TELEHEALTH",  "Telehealth"

    patient_id          = models.CharField(max_length=64, db_index=True)
    appointment_id      = models.CharField(max_length=64, db_index=True)
    event_type          = models.CharField(max_length=3,  choices=EventType.choices, db_index=True)
    appointment_dt      = models.DateTimeField()
    duration_minutes    = models.PositiveSmallIntegerField(default=30)
    appointment_type    = models.CharField(
        max_length=16, choices=AppointmentType.choices, default=AppointmentType.ROUTINE,
    )
    provider_id         = models.CharField(max_length=64, blank=True, default="")
    provider_name       = models.CharField(max_length=128, blank=True, default="")
    location            = models.CharField(max_length=64,  blank=True, default="")
    reason              = models.CharField(max_length=128, blank=True, default="")
    status              = models.CharField(
        max_length=16, choices=Status.choices, default=Status.GENERATED, db_index=True,
    )
    raw_hl7             = models.TextField()
    timestamp           = models.DateTimeField(auto_now_add=True, db_index=True)
    note                = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["-timestamp"]
        indexes  = [
            models.Index(fields=["patient_id", "appointment_dt"]),
            models.Index(fields=["status", "timestamp"]),
        ]

    def __str__(self):
        return f"SIU^{self.event_type} appt={self.appointment_id} patient={self.patient_id}"
