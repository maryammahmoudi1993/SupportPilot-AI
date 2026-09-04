"""Stuck-worker recovery for evaluation runs/cases (Phase 16 Checkpoint 2
Part C). Timestamps are controlled directly rather than sleeping in real
time, per the checkpoint's "do not wait in real time" instruction.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from evaluations.models import (
    EvaluationFailureCode,
    EvaluationResult,
    EvaluationResultStatus,
    EvaluationRun,
    EvaluationRunStatus,
)
from evaluations.recovery import recover_stuck_evaluation_runs

from .factories import EvaluationCaseSnapshotFactory, EvaluationResultFactory, EvaluationRunFactory

pytestmark = pytest.mark.django_db


def _age_run(run: EvaluationRun, seconds: int) -> None:
    EvaluationRun.objects.filter(pk=run.pk).update(
        updated_at=timezone.now() - timedelta(seconds=seconds)
    )


def _age_result(result: EvaluationResult, seconds: int) -> None:
    EvaluationResult.objects.filter(pk=result.pk).update(
        updated_at=timezone.now() - timedelta(seconds=seconds)
    )


def _make_stuck_run(*, total_cases=1, seconds=10_000):
    run = EvaluationRunFactory(status=EvaluationRunStatus.RUNNING, total_cases=total_cases)
    results = []
    for i in range(total_cases):
        snapshot = EvaluationCaseSnapshotFactory(run=run, sequence=i, case_key=f"case-{i}")
        result = EvaluationResultFactory(
            run=run, case_snapshot=snapshot, status=EvaluationResultStatus.RUNNING
        )
        _age_result(result, seconds)
        results.append(result)
    _age_run(run, seconds)
    return run, results


class TestRecoverStuckEvaluationRuns:
    def test_not_stale_running_run_is_untouched(self):
        run, results = _make_stuck_run(seconds=1)

        recovered = recover_stuck_evaluation_runs()

        run.refresh_from_db()
        assert recovered == 0
        assert run.status == EvaluationRunStatus.RUNNING

    def test_stale_running_case_is_failed_and_run_finalized(self):
        run, (result,) = _make_stuck_run(total_cases=1)

        recovered = recover_stuck_evaluation_runs()

        run.refresh_from_db()
        result.refresh_from_db()
        assert recovered == 1
        assert result.status == EvaluationResultStatus.FAILED
        assert result.failure_code == EvaluationFailureCode.WORKER_CRASH_RECOVERED
        assert result.passed is False
        # All (one) cases failed -> run finalizes FAILED (matches
        # finalize_evaluation_run's own "all cases failed" rule).
        assert run.status == EvaluationRunStatus.FAILED
        assert run.completed_cases == 1
        assert run.failed_cases == 1

    def test_partial_outcome_when_only_some_cases_are_stuck(self):
        run, (stuck, healthy) = _make_stuck_run(total_cases=2, seconds=0)
        # Only the first case is actually stuck; the second already
        # succeeded (as a real worker would have left it) before the crash.
        _age_result(stuck, 10_000)
        healthy.status = EvaluationResultStatus.SUCCEEDED
        healthy.passed = True
        healthy.save()
        _age_run(run, 10_000)

        recovered = recover_stuck_evaluation_runs()

        run.refresh_from_db()
        assert recovered == 1
        assert run.status == EvaluationRunStatus.PARTIAL
        assert run.completed_cases == 2
        assert run.passed_cases == 1
        assert run.failed_cases == 1

    @pytest.mark.parametrize(
        "status",
        [
            EvaluationRunStatus.SUCCEEDED,
            EvaluationRunStatus.PARTIAL,
            EvaluationRunStatus.FAILED,
            EvaluationRunStatus.CANCELLED,
            EvaluationRunStatus.PENDING,
        ],
    )
    def test_only_running_status_is_ever_a_recovery_candidate(self, status):
        run = EvaluationRunFactory(status=status, total_cases=0)
        _age_run(run, 10_000)

        recovered = recover_stuck_evaluation_runs()

        run.refresh_from_db()
        assert recovered == 0
        assert run.status == status

    def test_recovery_invoked_twice_is_idempotent(self):
        run, (result,) = _make_stuck_run(total_cases=1)

        first = recover_stuck_evaluation_runs()
        second = recover_stuck_evaluation_runs()

        run.refresh_from_db()
        result.refresh_from_db()
        assert first == 1
        assert second == 0
        assert run.status == EvaluationRunStatus.FAILED
        assert result.status == EvaluationResultStatus.FAILED

    def test_terminal_run_is_never_touched_even_if_stale(self):
        run = EvaluationRunFactory(status=EvaluationRunStatus.CANCELLED, total_cases=1)
        snapshot = EvaluationCaseSnapshotFactory(run=run)
        result = EvaluationResultFactory(
            run=run, case_snapshot=snapshot, status=EvaluationResultStatus.CANCELLED
        )
        _age_run(run, 10_000)
        _age_result(result, 10_000)

        recovered = recover_stuck_evaluation_runs()

        run.refresh_from_db()
        result.refresh_from_db()
        assert recovered == 0
        assert run.status == EvaluationRunStatus.CANCELLED
        assert result.status == EvaluationResultStatus.CANCELLED

    def test_completed_case_is_not_clobbered(self):
        """A case that already finished before the crash (only the run's
        own counter update / finalize call was lost) must be left exactly
        as it is — recovery only ever fails still-RUNNING cases."""
        run, (result,) = _make_stuck_run(total_cases=1, seconds=0)
        result.status = EvaluationResultStatus.SUCCEEDED
        result.passed = True
        result.save()
        _age_run(run, 10_000)
        # run.completed_cases/passed_cases were never updated (simulating
        # the crash between the result write and _record_case_completion).

        recovered = recover_stuck_evaluation_runs()

        run.refresh_from_db()
        result.refresh_from_db()
        assert recovered == 1
        assert result.status == EvaluationResultStatus.SUCCEEDED
        assert result.failure_code == ""
        assert run.status == EvaluationRunStatus.SUCCEEDED
        assert run.completed_cases == 1
        assert run.passed_cases == 1

    def test_batch_size_bounds_a_single_sweep(self):
        runs = [_make_stuck_run(total_cases=1)[0] for _ in range(3)]

        recovered = recover_stuck_evaluation_runs(batch_size=2)

        statuses = list(
            EvaluationRun.objects.filter(pk__in=[r.pk for r in runs]).values_list(
                "status", flat=True
            )
        )
        assert recovered == 2
        assert statuses.count(EvaluationRunStatus.RUNNING) == 1
        assert statuses.count(EvaluationRunStatus.FAILED) == 2
