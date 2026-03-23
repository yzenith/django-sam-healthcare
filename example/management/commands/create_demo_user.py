"""
Management command: create_demo_user

Creates (or resets) the demo user so anyone evaluating the project
can log in without running createsuperuser.

Usage:
    python manage.py create_demo_user

On Vercel, add this to your build command after migrate:
    python manage.py migrate && python manage.py create_demo_user
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

DEMO_USERNAME = "demo"
DEMO_PASSWORD = "demo1234"


class Command(BaseCommand):
    help = "Create or reset the demo user (username=demo, password=demo1234)"

    def handle(self, *args, **options):
        User = get_user_model()
        user, created = User.objects.get_or_create(username=DEMO_USERNAME)
        user.set_password(DEMO_PASSWORD)
        user.is_staff = False
        user.is_superuser = False
        user.save()

        action = "Created" if created else "Reset password for"
        self.stdout.write(
            self.style.SUCCESS(f"{action} demo user: {DEMO_USERNAME} / {DEMO_PASSWORD}")
        )
