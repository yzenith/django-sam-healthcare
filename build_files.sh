#!/usr/bin/env bash
# Vercel build script for Django
set -e

# Create a Python 3.12 venv and install packages there.
# We must unset PYTHONPATH after activation to prevent Vercel's auto-installed
# packages (compiled for Python 3.14) from shadowing the venv packages.
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements.txt
unset PYTHONPATH

# collectstatic/migrate don't sign or verify anything user-facing, so an
# ephemeral build-only secret is fine here. The deployed serving function
# still requires the real DJANGO_SECRET_KEY/MIRTH_JWT_SECRET to be set as
# Vercel project env vars — settings.py hard-fails at request time without them.
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')}"
export MIRTH_JWT_SECRET="${MIRTH_JWT_SECRET:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')}"

python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py create_demo_user
python manage.py seed_demo_data
