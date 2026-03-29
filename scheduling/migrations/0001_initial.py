from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="SIUMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("patient_id",       models.CharField(db_index=True, max_length=64)),
                ("appointment_id",   models.CharField(db_index=True, max_length=64)),
                ("event_type",       models.CharField(
                    choices=[("S12","S12 – New Appointment"),("S14","S14 – Appointment Modified"),("S15","S15 – Appointment Cancelled")],
                    db_index=True, max_length=3,
                )),
                ("appointment_dt",   models.DateTimeField()),
                ("duration_minutes", models.PositiveSmallIntegerField(default=30)),
                ("appointment_type", models.CharField(
                    choices=[("ROUTINE","Routine"),("URGENT","Urgent"),("WALK_IN","Walk-In"),("FOLLOW_UP","Follow-Up"),("TELEHEALTH","Telehealth")],
                    default="ROUTINE", max_length=16,
                )),
                ("provider_id",      models.CharField(blank=True, default="", max_length=64)),
                ("provider_name",    models.CharField(blank=True, default="", max_length=128)),
                ("location",         models.CharField(blank=True, default="", max_length=64)),
                ("reason",           models.CharField(blank=True, default="", max_length=128)),
                ("status",           models.CharField(
                    choices=[("GENERATED","Generated"),("SENT","Sent"),("FAILED","Failed")],
                    db_index=True, default="GENERATED", max_length=16,
                )),
                ("raw_hl7",          models.TextField()),
                ("timestamp",        models.DateTimeField(auto_now_add=True, db_index=True)),
                ("note",             models.CharField(blank=True, default="", max_length=255)),
            ],
            options={"ordering": ["-timestamp"]},
        ),
        migrations.AddIndex(
            model_name="siumessage",
            index=models.Index(fields=["patient_id", "appointment_dt"], name="siu_patient_appt_idx"),
        ),
        migrations.AddIndex(
            model_name="siumessage",
            index=models.Index(fields=["status", "timestamp"], name="siu_status_ts_idx"),
        ),
    ]
