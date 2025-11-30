from django.db import models

class HL7MessageLog(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    source_system = models.CharField(max_length=50, blank=True)
    message_type = models.CharField(max_length=20, blank=True)
    raw_hl7 = models.TextField()
    patient_id = models.CharField(max_length=64, blank=True)
    encounter_present = models.BooleanField(default=False)
    x12_length = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.created_at} {self.message_type} {self.patient_id}"
