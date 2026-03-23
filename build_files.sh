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

python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py create_demo_user
python manage.py seed_demo_data
