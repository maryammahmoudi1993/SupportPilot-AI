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

# Phase 8 (section 45): a periodic sweep for approval requests whose
# expires_at has passed while nobody decided them. Deliberately coarse —
# expiry is also enforced synchronously on read/decide/resume (section 44),
# so this beat schedule only needs to catch requests nobody ever looked at
# again. No business logic lives here; the task calls
# ``approvals.services.expire_stale_approvals``.
app.conf.beat_schedule = {
    "expire-stale-approvals": {
        "task": "approvals.tasks.expire_stale_approvals_task",
        "schedule": 300.0,  # every 5 minutes
    },
}
