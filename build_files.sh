#!/usr/bin/env bash
# Vercel build script for Django
set -e

uv pip install -r requirements.txt --system

python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py create_demo_user
python manage.py seed_demo_data
