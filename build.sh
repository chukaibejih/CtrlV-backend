#!/usr/bin/env bash

set -o errexit  # Exit immediately if a command exits with a non-zero status

# Install dependencies using Poetry
poetry install --no-root

# Collect static files
poetry run python manage.py collectstatic --no-input

# Run migrations
poetry run python manage.py migrate

# Create superuser from environment variables (optional)
# poetry run python manage.py create_superuser
