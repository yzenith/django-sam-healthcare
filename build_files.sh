#!/usr/bin/env bash
# Vercel build script for Django
# NOTE: Vercel installs requirements.txt automatically via uv — do not duplicate here.
set -e

python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py create_demo_user
python manage.py seed_demo_data
