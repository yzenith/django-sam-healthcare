from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="SFTPIngestRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("filename", models.CharField(blank=True, default="", max_length=255)),
                ("status", models.CharField(
                    choices=[("RECEIVED", "Received"), ("COMPLETED", "Completed"), ("FAILED", "Failed")],
                    db_index=True, default="RECEIVED", max_length=16,
                )),
                ("schema_type", models.CharField(
                    choices=[("PATIENT", "Patient Demographics"), ("CLINICAL", "Clinical Records"), ("UNKNOWN", "Unknown")],
                    default="UNKNOWN", max_length=16,
                )),
                ("detected_delimiter", models.CharField(
                    choices=[("COMMA", "CSV (comma-separated)"), ("PIPE", "Pipe-delimited (|)"), ("TAB", "Tab-delimited")],
                    default="COMMA", max_length=8,
                )),
                ("total_rows", models.IntegerField(default=0)),
                ("valid_rows", models.IntegerField(default=0)),
                ("inserted", models.IntegerField(default=0)),
                ("updated", models.IntegerField(default=0)),
                ("rejected", models.IntegerField(default=0)),
                ("duplicates_in_file", models.IntegerField(default=0)),
                ("validation_errors", models.JSONField(blank=True, default=list)),
                ("processing_summary", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True, default="")),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [models.Index(fields=["status", "created_at"], name="sftpingest_status_created_idx")],
            },
        ),
        migrations.CreateModel(
            name="ClinicalRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ingest_run", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="clinical_records",
                    to="sftpingest.sftpingestrun",
                )),
                ("mrn", models.CharField(db_index=True, max_length=64)),
                ("visit_date", models.DateField(blank=True, null=True)),
                ("visit_type", models.CharField(blank=True, default="", max_length=32)),
                ("diagnosis_code", models.CharField(blank=True, default="", max_length=16)),
                ("procedure_code", models.CharField(blank=True, default="", max_length=16)),
                ("provider_id", models.CharField(blank=True, default="", max_length=32)),
                ("facility_code", models.CharField(blank=True, default="", max_length=32)),
                ("notes", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="clinicalrecord",
            index=models.Index(fields=["mrn", "visit_date"], name="sftpingest_mrn_visit_idx"),
        ),
        migrations.AddIndex(
            model_name="clinicalrecord",
            index=models.Index(fields=["ingest_run", "mrn"], name="sftpingest_run_mrn_idx"),
        ),
    ]
