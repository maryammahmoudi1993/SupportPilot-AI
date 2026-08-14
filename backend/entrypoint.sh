#!/bin/sh
set -e

# Migrations are an explicit release step, not run automatically here, to
# avoid concurrent web/worker replicas racing schema changes on startup.
# Run `python manage.py migrate` via the deployment platform's release
# command instead.

exec "$@"
