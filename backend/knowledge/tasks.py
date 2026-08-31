"""Thin Celery boundary for knowledge ingestion."""

from celery import shared_task
from django.conf import settings

from common.tasks import CorrelatedTask

from .errors import RetryableIngestionError
from .services import fail_ingestion, ingestion_attempt_count, run_ingestion


@shared_task(bind=True, base=CorrelatedTask, max_retries=None)
def ingest_knowledge_document(self, job_id: str, correlation_id: str | None = None):
    # ``correlation_id`` is declared only so Celery's argument validation
    # accepts it from ``_dispatch_ingestion`` — see the identical note on
    # ``agents.tasks.execute_agent_run_task`` (Phase 11 Block 2).
    try:
        return run_ingestion(job_id=job_id).__dict__
    except RetryableIngestionError as exc:
        max_attempts = settings.KNOWLEDGE_INGESTION_MAX_ATTEMPTS
        if ingestion_attempt_count(job_id) >= max_attempts:
            fail_ingestion(job_id, exc)
            return {"job_id": job_id, "status": "failed", "chunk_count": 0}
        raise self.retry(exc=exc, countdown=min(60, 2**self.request.retries)) from exc
