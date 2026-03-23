"""
Management command: seed_demo_data

Populates the database with realistic synthetic HL7 demo records so the UI
looks like a live system instead of empty tables when recruiters first land.

Usage:
    python manage.py seed_demo_data           # idempotent — skips if data exists
    python manage.py seed_demo_data --clear   # wipe existing SEED records first

On Vercel, add after migrate + create_demo_user in the build command:
    python manage.py migrate && \
    python manage.py create_demo_user && \
    python manage.py seed_demo_data
"""
from django.core.management.base import BaseCommand
from example.seed_demo import seed_demo_data


class Command(BaseCommand):
    help = "Seed the database with realistic demo HL7 / claim / webhook records"

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            default=False,
            help="Delete existing SEED records before inserting fresh ones",
        )

    def handle(self, *args, **options):
        result = seed_demo_data(clear_existing=options["clear"])

        if result.get("skipped"):
            self.stdout.write(self.style.WARNING(
                f"Skipped: {result['reason']}"
            ))
            return

        self.stdout.write(self.style.SUCCESS(
            f"Seeded: {result['messages']} messages, "
            f"{result['claims']} claims, "
            f"{result['webhooks']} webhook deliveries"
        ))
