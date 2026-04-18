import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("example", "0008_webhook_retry_fields"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # --- OAuthClient ---
        migrations.CreateModel(
            name="OAuthClient",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("client_id", models.CharField(default=uuid.uuid4, max_length=100, unique=True)),
                ("client_secret_hash", models.CharField(blank=True, max_length=255)),
                ("client_name", models.CharField(max_length=200)),
                ("redirect_uris", models.JSONField(default=list)),
                ("scopes_allowed", models.JSONField(default=list)),
                ("grant_types", models.JSONField(default=list)),
                ("is_public", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        # --- OAuthAuthCode ---
        migrations.CreateModel(
            name="OAuthAuthCode",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=128, unique=True)),
                ("client", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to="example.oauthclient",
                )),
                ("user", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    to=settings.AUTH_USER_MODEL,
                )),
                ("redirect_uri", models.TextField()),
                ("scopes", models.JSONField(default=list)),
                ("patient_context", models.CharField(blank=True, max_length=100)),
                ("code_challenge", models.CharField(blank=True, max_length=255)),
                ("code_challenge_method", models.CharField(blank=True, default="S256", max_length=10)),
                ("expires_at", models.DateTimeField()),
                ("used", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        # --- OAuthToken ---
        migrations.CreateModel(
            name="OAuthToken",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("access_token", models.TextField(unique=True)),
                ("client", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to="example.oauthclient",
                )),
                ("user", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    to=settings.AUTH_USER_MODEL,
                )),
                ("scopes", models.JSONField(default=list)),
                ("patient_context", models.CharField(blank=True, max_length=100)),
                ("expires_at", models.DateTimeField()),
                ("refresh_token", models.CharField(blank=True, db_index=True, max_length=255)),
                ("refresh_expires_at", models.DateTimeField(blank=True, null=True)),
                ("revoked", models.BooleanField(db_index=True, default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["revoked", "expires_at"], name="example_oau_revoked_idx"),
                ],
            },
        ),
        # --- BulkExportJob ---
        migrations.CreateModel(
            name="BulkExportJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("job_id", models.UUIDField(db_index=True, default=uuid.uuid4, unique=True)),
                ("resource_type", models.CharField(default="Patient", max_length=100)),
                ("status", models.CharField(
                    choices=[
                        ("pending", "Pending"),
                        ("running", "Running"),
                        ("complete", "Complete"),
                        ("error", "Error"),
                    ],
                    default="complete",
                    max_length=20,
                )),
                ("output_files", models.JSONField(default=list)),
                ("ndjson_data", models.JSONField(default=dict)),
                ("error", models.TextField(blank=True)),
                ("since", models.DateTimeField(blank=True, null=True)),
                ("requested_by", models.CharField(blank=True, max_length=100)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
            ],
        ),
    ]
