"""Celery application for SupportPilot AI.

Business logic must not live in task bodies — tasks call service functions
defined in each domain app, per the project's architecture rules.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("supportpilot")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
