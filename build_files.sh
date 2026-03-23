#!/usr/bin/env bash
# Vercel build script for Django
set -e

# Create a venv with Python 3.12 so management commands can find packages.
# Vercel marks all system Pythons as externally managed, so --system is blocked.
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements.txt

python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py create_demo_user
python manage.py seed_demo_data
