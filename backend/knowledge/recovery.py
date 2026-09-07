"""Stuck-job recovery for ``KnowledgeIngestionJob`` (Phase 17 final acceptance
gate, Part B).

The final Celery task-durability inventory found this was the one critical
async workflow with a durable PostgreSQL row (``KnowledgeIngestionJob``) but
no periodic recovery path — unlike ``agents``/``evaluations``/
``channel_ingress``/``notifications``. Two failure modes are both real
possibilities with ``task_acks_late`` unset (default False):

* a job's *only* publication attempt was the ``transaction.on_commit`` call
  in ``upload_document``/``retry_document`` — if that Celery ``.delay()``
  never reached the broker, or the broker message was lost before any
  worker claimed it, the row is left ``queued`` forever with nothing to
  re-publish it (the existing ``retry_document`` API path only accepts a
  document already ``failed`` — a stuck ``queued`` row never gets there);
* a worker that claimed a job (``run_ingestion`` set it ``processing``) and
  then crashed leaves it ``processing`` forever for the same reason.

Recovery here is a re-publish, not a re-execution of ingestion logic itself:
``run_ingestion`` (knowledge/services.py) already short-circuits on
``SUCCEEDED`` and is safe to invoke more than once for the same job id (its
own row lock is the single point of truth), exactly as
``notifications.recovery`` only ever re-publishes a delivery id into the
same claim-then-handle boundary. This module never touches document/chunk
content and performs no extraction/embedding itself.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from observability.metrics import observe_stuck_run_recovery

from .models import KnowledgeIngestionJob, KnowledgeIngestionStatus

logger = logging.getLogger("supportpilot")


def recover_stuck_ingestion_jobs(*, batch_size: int | None = None, now=None) -> int:
    """Re-publish ``KnowledgeIngestionJob`` rows stuck past the staleness
    threshold in either ``queued`` (never claimed) or ``processing`` (worker
    died mid-job) state.

    Returns the number of jobs re-published. Safe to call repeatedly and
    from more than one scheduler at once: this only calls ``.delay()`` again
    for a candidate id — all correctness comes from ``run_ingestion``'s own
    row lock, never from anything in this module.
    """
    now = now or timezone.now()
    cutoff = now - timedelta(seconds=settings.KNOWLEDGE_STUCK_JOB_STALE_SECONDS)
    batch_size = (
        batch_size if batch_size is not None else settings.KNOWLEDGE_STUCK_JOB_SWEEP_BATCH_SIZE
    )
    stuck_queued = KnowledgeIngestionJob.objects.filter(
        status=KnowledgeIngestionStatus.QUEUED, created_at__lte=cutoff
    )
    stuck_processing = KnowledgeIngestionJob.objects.filter(
        status=KnowledgeIngestionStatus.PROCESSING, started_at__lte=cutoff
    )
    job_ids = list(
        (stuck_queued | stuck_processing)
        .order_by("created_at")
        .values_list("id", flat=True)[:batch_size]
    )
    for job_id in job_ids:
        _redispatch(job_id)
    if job_ids:
        logger.info(
            "knowledge_stuck_ingestion_job_recovered",
            extra={"event": "knowledge_stuck_ingestion_job_recovered", "count": len(job_ids)},
        )
        observe_stuck_run_recovery(domain="knowledge_ingestion", count=len(job_ids))
    return len(job_ids)


def _redispatch(job_id) -> None:
    from .services import _dispatch_ingestion

    _dispatch_ingestion(job_id)
