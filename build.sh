#!/usr/bin/env bash

set -o errexit  # Exit immediately if a command exits with a non-zero status

# Ensure Poetry is available
if ! command -v poetry &> /dev/null; then
    echo "Poetry not found, exiting..."
    exit 1
fi

# Use local .venv instead of system-wide location
poetry config virtualenvs.in-project true

# Install dependencies
poetry install --no-root

# Run migrations
poetry run python manage.py migrate

# Create superuser
poetry run python manage.py create_superuser
