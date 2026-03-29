import uuid
from django.db import models
from example.models import PatientRecord


class CCDADocument(models.Model):
    """
    One generated C-CDA R2.1 document tied to a PatientRecord.

    The xml_content field holds the full, well-formed ClinicalDocument XML.
    Stored so the document can be retrieved and downloaded without re-generating.
    """

    class DocumentType(models.TextChoices):
        CCD              = "CCD",              "Continuity of Care Document (CCD)"
        DISCHARGE        = "DISCHARGE_SUMMARY", "Discharge Summary"
        PROGRESS_NOTE    = "PROGRESS_NOTE",    "Progress Note"

    patient       = models.ForeignKey(
        PatientRecord, on_delete=models.CASCADE, related_name="ccda_documents",
    )
    document_type = models.CharField(
        max_length=32, choices=DocumentType.choices, default=DocumentType.CCD,
    )
    document_id   = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    created_at    = models.DateTimeField(auto_now_add=True, db_index=True)
    xml_content   = models.TextField()

    class Meta:
        ordering = ["-created_at"]
        indexes  = [models.Index(fields=["patient", "created_at"])]

    def __str__(self):
        return f"C-CDA {self.document_type} mrn={self.patient.mrn} [{self.document_id}]"
