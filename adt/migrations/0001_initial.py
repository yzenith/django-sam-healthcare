from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ADTMessage",
            fields=[
                ("id",         models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("patient_id", models.CharField(db_index=True, max_length=64)),
                ("event_type", models.CharField(
                    choices=[
                        ("A01", "A01 \u2013 Admit Patient"),
                        ("A02", "A02 \u2013 Transfer Patient"),
                        ("A03", "A03 \u2013 Discharge Patient"),
                        ("A08", "A08 \u2013 Update Patient Info"),
                    ],
                    db_index=True,
                    max_length=3,
                )),
                ("timestamp",  models.DateTimeField(auto_now_add=True, db_index=True)),
                ("raw_hl7",    models.TextField()),
                ("status",     models.CharField(
                    choices=[
                        ("GENERATED", "Generated"),
                        ("SENT",      "Sent"),
                        ("FAILED",    "Failed"),
                    ],
                    db_index=True,
                    default="GENERATED",
                    max_length=16,
                )),
                ("facility",   models.CharField(blank=True, default="", max_length=64)),
                ("location",   models.CharField(blank=True, default="", max_length=64)),
                ("note",       models.CharField(blank=True, default="", max_length=255)),
            ],
            options={
                "ordering": ["-timestamp"],
            },
        ),
        migrations.AddIndex(
            model_name="adtmessage",
            index=models.Index(fields=["event_type", "timestamp"], name="adt_adtmess_event_t_idx"),
        ),
        migrations.AddIndex(
            model_name="adtmessage",
            index=models.Index(fields=["status", "timestamp"], name="adt_adtmess_status_idx"),
        ),
        migrations.AddIndex(
            model_name="adtmessage",
            index=models.Index(fields=["patient_id", "timestamp"], name="adt_adtmess_patient_idx"),
        ),
    ]
