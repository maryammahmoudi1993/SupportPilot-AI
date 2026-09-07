"""Stuck-job recovery for ``KnowledgeIngestionJob`` (Phase 17 final
acceptance gate, Part B).

Timestamps are controlled directly (``queryset.update(...)`` bypasses
``auto_now_add``/manual field assignment the same way a real stuck row would
have been left by a lost broker message or a crashed worker) rather than
sleeping in real time, mirroring ``agents/tests/test_recovery.py``.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from knowledge.models import KnowledgeIngestionJob, KnowledgeIngestionStatus
from knowledge.recovery import recover_stuck_ingestion_jobs

from .factories import KnowledgeIngestionJobFactory

pytestmark = pytest.mark.django_db


def _age_created(job: KnowledgeIngestionJob, seconds: int) -> None:
    KnowledgeIngestionJob.objects.filter(pk=job.pk).update(
        created_at=timezone.now() - timedelta(seconds=seconds)
    )


def _age_started(job: KnowledgeIngestionJob, seconds: int) -> None:
    KnowledgeIngestionJob.objects.filter(pk=job.pk).update(
        started_at=timezone.now() - timedelta(seconds=seconds)
    )


class TestRecoverStuckIngestionJobs:
    def test_fresh_queued_job_is_untouched(self):
        job = KnowledgeIngestionJobFactory(status=KnowledgeIngestionStatus.QUEUED)
        _age_created(job, seconds=1)  # well under the default 600s threshold

        with patch("knowledge.recovery._redispatch") as redispatch:
            recovered = recover_stuck_ingestion_jobs()

        assert recovered == 0
        redispatch.assert_not_called()

    def test_fresh_processing_job_is_untouched(self):
        job = KnowledgeIngestionJobFactory(status=KnowledgeIngestionStatus.PROCESSING)
        _age_started(job, seconds=1)

        with patch("knowledge.recovery._redispatch") as redispatch:
            recovered = recover_stuck_ingestion_jobs()

        assert recovered == 0
        redispatch.assert_not_called()

    def test_stale_queued_job_is_redispatched(self):
        job = KnowledgeIngestionJobFactory(status=KnowledgeIngestionStatus.QUEUED)
        _age_created(job, seconds=601)

        with patch("knowledge.recovery._redispatch") as redispatch:
            recovered = recover_stuck_ingestion_jobs()

        assert recovered == 1
        redispatch.assert_called_once_with(job.id)

    def test_stale_processing_job_is_redispatched(self):
        job = KnowledgeIngestionJobFactory(status=KnowledgeIngestionStatus.PROCESSING)
        _age_started(job, seconds=601)

        with patch("knowledge.recovery._redispatch") as redispatch:
            recovered = recover_stuck_ingestion_jobs()

        assert recovered == 1
        redispatch.assert_called_once_with(job.id)

    def test_succeeded_and_failed_jobs_are_never_candidates(self):
        succeeded = KnowledgeIngestionJobFactory(status=KnowledgeIngestionStatus.SUCCEEDED)
        failed = KnowledgeIngestionJobFactory(status=KnowledgeIngestionStatus.FAILED)
        _age_created(succeeded, seconds=99999)
        _age_created(failed, seconds=99999)

        with patch("knowledge.recovery._redispatch") as redispatch:
            recovered = recover_stuck_ingestion_jobs()

        assert recovered == 0
        redispatch.assert_not_called()

    def test_batch_size_is_respected(self):
        jobs = KnowledgeIngestionJobFactory.create_batch(3, status=KnowledgeIngestionStatus.QUEUED)
        for job in jobs:
            _age_created(job, seconds=601)

        with patch("knowledge.recovery._redispatch") as redispatch:
            recovered = recover_stuck_ingestion_jobs(batch_size=2)

        assert recovered == 2
        assert redispatch.call_count == 2

    def test_recovery_is_safe_to_run_twice_in_a_row(self):
        """A second sweep (e.g. from a duplicate scheduler) simply
        re-publishes the same still-stuck id again — no state here makes
        that unsafe; correctness lives entirely in ``run_ingestion``'s own
        row lock (see the module docstring)."""
        job = KnowledgeIngestionJobFactory(status=KnowledgeIngestionStatus.QUEUED)
        _age_created(job, seconds=601)

        with patch("knowledge.recovery._redispatch") as redispatch:
            first = recover_stuck_ingestion_jobs()
            second = recover_stuck_ingestion_jobs()

        assert first == 1
        assert second == 1
        assert redispatch.call_count == 2

    def test_redispatch_calls_the_real_ingestion_dispatch_boundary(self):
        job = KnowledgeIngestionJobFactory(status=KnowledgeIngestionStatus.QUEUED)
        _age_created(job, seconds=601)

        with patch("knowledge.services._dispatch_ingestion") as dispatch:
            recovered = recover_stuck_ingestion_jobs()

        assert recovered == 1
        dispatch.assert_called_once_with(job.id)
