from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("adt", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="DFTMessage",
            fields=[
                ("id",            models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("patient_id",    models.CharField(db_index=True, max_length=64)),
                ("encounter_id",  models.CharField(blank=True, db_index=True, default="", max_length=64)),
                ("trigger_event", models.CharField(
                    choices=[
                        ("A01",    "A01 \u2013 Admit (room/bed charges)"),
                        ("A03",    "A03 \u2013 Discharge (service finalization)"),
                        ("MANUAL", "Manual trigger"),
                    ],
                    default="MANUAL",
                    max_length=8,
                )),
                ("timestamp",     models.DateTimeField(auto_now_add=True, db_index=True)),
                ("raw_hl7",       models.TextField()),
                ("status",        models.CharField(
                    choices=[("GENERATED", "Generated"), ("SENT", "Sent"), ("FAILED", "Failed")],
                    db_index=True,
                    default="GENERATED",
                    max_length=16,
                )),
                ("total_charges", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("claim_id",      models.CharField(blank=True, db_index=True, default="", max_length=64)),
                ("x12_837",       models.TextField(blank=True, default="")),
                ("adt_message",   models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="dft_messages",
                    to="adt.adtmessage",
                )),
            ],
            options={"ordering": ["-timestamp"]},
        ),
        migrations.AddIndex(
            model_name="dftmessage",
            index=models.Index(fields=["patient_id", "timestamp"], name="adt_dftmess_patient_idx"),
        ),
        migrations.AddIndex(
            model_name="dftmessage",
            index=models.Index(fields=["status", "timestamp"], name="adt_dftmess_status_idx"),
        ),
        migrations.AddIndex(
            model_name="dftmessage",
            index=models.Index(fields=["trigger_event", "timestamp"], name="adt_dftmess_trigger_idx"),
        ),
        migrations.CreateModel(
            name="DFTChargeItem",
            fields=[
                ("id",                    models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("line_number",           models.PositiveSmallIntegerField()),
                ("charge_id",             models.CharField(blank=True, default="", max_length=64)),
                ("encounter_batch",       models.CharField(blank=True, default="", max_length=64)),
                ("service_date",          models.DateField(blank=True, null=True)),
                ("transaction_type",      models.CharField(
                    choices=[("CG", "Charge"), ("CR", "Credit"), ("PY", "Payment")],
                    default="CG",
                    max_length=2,
                )),
                ("unit_amount",           models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("quantity",              models.PositiveSmallIntegerField(default=1)),
                ("total_amount",          models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("procedure_code",        models.CharField(blank=True, default="", max_length=16)),
                ("procedure_description", models.CharField(blank=True, default="", max_length=128)),
                ("revenue_code",          models.CharField(blank=True, default="", max_length=8)),
                ("department",            models.CharField(blank=True, default="", max_length=32)),
                ("insurance_plan",        models.CharField(blank=True, default="", max_length=64)),
                ("dft_message",           models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="charges",
                    to="adt.dftmessage",
                )),
            ],
            options={"ordering": ["dft_message", "line_number"]},
        ),
    ]
