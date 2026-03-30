import uuid
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True
    dependencies = [
        ("example", "0005_patientimportrun_patientrecord"),
    ]

    operations = [
        migrations.CreateModel(
            name="CCDADocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("patient", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="ccda_documents",
                    to="example.patientrecord",
                )),
                ("document_type", models.CharField(
                    choices=[
                        ("CCD", "Continuity of Care Document (CCD)"),
                        ("DISCHARGE_SUMMARY", "Discharge Summary"),
                        ("PROGRESS_NOTE", "Progress Note"),
                    ],
                    default="CCD", max_length=32,
                )),
                ("document_id", models.UUIDField(default=uuid.uuid4, db_index=True, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("xml_content", models.TextField()),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="ccdadocument",
            index=models.Index(fields=["patient", "created_at"], name="ccda_patient_created_idx"),
        ),
    ]
