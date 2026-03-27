from django.db import models


class SFTPIngestRun(models.Model):
    """
    Audit record for one simulated SFTP flat-file ingestion job.

    One row per uploaded file.  Captures everything needed to answer
    operational questions: what file arrived, when, what happened to
    each row, and how long it took — mirroring what a production SFTP
    polling job would write to its run log.
    """

    class Status(models.TextChoices):
        RECEIVED  = "RECEIVED",  "Received"
        COMPLETED = "COMPLETED", "Completed"
        FAILED    = "FAILED",    "Failed"

    class SchemaType(models.TextChoices):
        PATIENT  = "PATIENT",  "Patient Demographics"
        CLINICAL = "CLINICAL", "Clinical Records"
        UNKNOWN  = "UNKNOWN",  "Unknown"

    class Delimiter(models.TextChoices):
        COMMA = "COMMA", "CSV (comma-separated)"
        PIPE  = "PIPE",  "Pipe-delimited (|)"
        TAB   = "TAB",   "Tab-delimited"

    created_at          = models.DateTimeField(auto_now_add=True, db_index=True)
    filename            = models.CharField(max_length=255, blank=True, default="")
    status              = models.CharField(
        max_length=16, choices=Status.choices, default=Status.RECEIVED, db_index=True
    )
    schema_type         = models.CharField(
        max_length=16, choices=SchemaType.choices, default=SchemaType.UNKNOWN
    )
    detected_delimiter  = models.CharField(
        max_length=8, choices=Delimiter.choices, default=Delimiter.COMMA
    )

    # Row-level counters
    total_rows          = models.IntegerField(default=0)
    valid_rows          = models.IntegerField(default=0)
    inserted            = models.IntegerField(default=0)
    updated             = models.IntegerField(default=0)
    rejected            = models.IntegerField(default=0)
    duplicates_in_file  = models.IntegerField(default=0)

    # Validation error log — list of {rownum, field, error, raw_value}
    validation_errors   = models.JSONField(default=list, blank=True)

    # Full reconciliation summary for the detail view
    processing_summary  = models.JSONField(default=dict, blank=True)

    # Top-level failure message (schema mismatch, encoding error, etc.)
    error_message       = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        indexes  = [models.Index(fields=["status", "created_at"])]

    def __str__(self):
        return f"SFTPIngestRun #{self.id} {self.filename} [{self.status}]"

    @property
    def reject_rate(self) -> float:
        return round(self.rejected / self.total_rows * 100, 1) if self.total_rows else 0.0

    @property
    def success_rate(self) -> float:
        return round(self.valid_rows / self.total_rows * 100, 1) if self.total_rows else 0.0


class ClinicalRecord(models.Model):
    """
    One clinical encounter/observation row parsed from an SFTP flat file.

    Patient demographics go into the existing PatientRecord model; this model
    captures encounter-level clinical data that doesn't fit the demographic
    schema — visit type, diagnosis, procedure, provider, and free-text notes.

    In a production system this would link to an Encounter in the FHIR layer;
    here it provides a standalone audit trail for the ingested clinical data.
    """

    ingest_run     = models.ForeignKey(
        SFTPIngestRun, on_delete=models.CASCADE, related_name="clinical_records"
    )
    mrn            = models.CharField(max_length=64, db_index=True)
    visit_date     = models.DateField(null=True, blank=True)
    visit_type     = models.CharField(max_length=32,  blank=True, default="")
    diagnosis_code = models.CharField(max_length=16,  blank=True, default="")
    procedure_code = models.CharField(max_length=16,  blank=True, default="")
    provider_id    = models.CharField(max_length=32,  blank=True, default="")
    facility_code  = models.CharField(max_length=32,  blank=True, default="")
    notes          = models.TextField(blank=True, default="")
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes  = [
            models.Index(fields=["mrn", "visit_date"]),
            models.Index(fields=["ingest_run", "mrn"]),
        ]

    def __str__(self):
        return f"ClinicalRecord mrn={self.mrn} {self.visit_date} {self.diagnosis_code}"
