from django.db import models


# ── ADT ───────────────────────────────────────────────────────────────────────

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


# ── DFT ───────────────────────────────────────────────────────────────────────

class DFTMessage(models.Model):
    """
    One DFT^P03 (Post Detail Financial Transaction) message per billing event.

    Triggered automatically when an ADT A01 (admit) or A03 (discharge) event
    is processed. Captures the charge data from FT1 segments and the resulting
    X12 837P professional claim string, completing the ADT → DFT → 837 revenue
    cycle loop.
    """

    class Status(models.TextChoices):
        GENERATED = "GENERATED", "Generated"
        SENT      = "SENT",      "Sent"
        FAILED    = "FAILED",    "Failed"

    class TriggerEvent(models.TextChoices):
        A01      = "A01",    "A01 – Admit (room/bed charges)"
        A03      = "A03",    "A03 – Discharge (service finalization)"
        MANUAL   = "MANUAL", "Manual trigger"

    # Link back to the ADT event that caused this billing message (nullable for
    # manually-triggered DFTs)
    adt_message   = models.ForeignKey(
        ADTMessage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dft_messages",
    )
    patient_id    = models.CharField(max_length=64, db_index=True)
    encounter_id  = models.CharField(max_length=64, blank=True, default="", db_index=True)
    trigger_event = models.CharField(
        max_length=8,
        choices=TriggerEvent.choices,
        default=TriggerEvent.MANUAL,
    )
    timestamp     = models.DateTimeField(auto_now_add=True, db_index=True)
    raw_hl7       = models.TextField()
    status        = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.GENERATED,
        db_index=True,
    )
    # Financial summary derived from FT1 segments
    total_charges = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    claim_id      = models.CharField(max_length=64, blank=True, default="", db_index=True)
    # Downstream X12 837P claim (generated at DFT creation time)
    x12_837       = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["patient_id", "timestamp"]),
            models.Index(fields=["status", "timestamp"]),
            models.Index(fields=["trigger_event", "timestamp"]),
        ]

    def __str__(self):
        return f"DFT^P03 pid={self.patient_id} claim={self.claim_id} [{self.status}]"


class DFTChargeItem(models.Model):
    """
    One row per FT1 segment in a DFT^P03 message.

    Maps directly to an X12 837 LX/SV1 service line — procedure code, amount,
    units, revenue code, and department — giving a full audit trail from
    clinical event to billing line item.
    """

    class TransactionType(models.TextChoices):
        CHARGE  = "CG", "Charge"
        CREDIT  = "CR", "Credit"
        PAYMENT = "PY", "Payment"

    dft_message          = models.ForeignKey(
        DFTMessage, on_delete=models.CASCADE, related_name="charges"
    )
    line_number          = models.PositiveSmallIntegerField()   # FT1-1 set ID
    charge_id            = models.CharField(max_length=64, blank=True, default="")  # FT1-2
    encounter_batch      = models.CharField(max_length=64, blank=True, default="")  # FT1-3
    service_date         = models.DateField(null=True, blank=True)                  # FT1-4
    transaction_type     = models.CharField(
        max_length=2, choices=TransactionType.choices, default=TransactionType.CHARGE
    )                                                                                # FT1-6
    unit_amount          = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # FT1-9
    quantity             = models.PositiveSmallIntegerField(default=1)              # FT1-8
    total_amount         = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # FT1-7
    procedure_code       = models.CharField(max_length=16, blank=True, default="")  # FT1-25 / FT1-11 CPT
    procedure_description = models.CharField(max_length=128, blank=True, default="")
    revenue_code         = models.CharField(max_length=8, blank=True, default="")
    department           = models.CharField(max_length=32, blank=True, default="")  # FT1-16
    insurance_plan       = models.CharField(max_length=64, blank=True, default="")  # FT1-17

    class Meta:
        ordering = ["dft_message", "line_number"]

    def __str__(self):
        return (
            f"FT1-{self.line_number} {self.procedure_code} "
            f"${self.total_amount} [{self.transaction_type}]"
        )
