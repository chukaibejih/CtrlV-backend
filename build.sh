#!/usr/bin/env bash

set -o errexit  # Exit immediately if a command exits with a non-zero status

# Install Poetry if not installed
if ! command -v poetry &> /dev/null; then
    curl -sSL https://install.python-poetry.org | python3 -
    export PATH="$HOME/.local/bin:$PATH"
fi

# Install dependencies using Poetry
poetry install --no-root

# Collect static files
# poetry run python manage.py collectstatic --no-input

# Run migrations
poetry run python manage.py migrate

# Create superuser from environment variables
poetry run python manage.py create_superuser
