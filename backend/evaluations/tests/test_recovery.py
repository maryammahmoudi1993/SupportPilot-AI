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
from evaluations.recovery import _recover_one_stuck_run, recover_stuck_evaluation_runs

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

    def test_healthy_worker_at_the_theoretical_worst_case_duration_is_not_recovered(self):
        """Phase 16 Checkpoint 2A section 13: a case executes through the
        same agent run-loop budgets as a normal AgentRun, so the same
        derived worst-case legitimate duration (900s — see
        agents/tests/test_recovery.py's equivalent test) applies here too.
        The default stale threshold (validated in settings.py to be
        >=1800s) comfortably clears it."""
        run, results = _make_stuck_run(seconds=900)

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

    def test_stale_parent_with_recent_child_progress_is_not_recovered(self):
        """Phase 16 Checkpoint 3 (Part A, matrix B): the run's own
        ``updated_at`` is stale purely because no case has *completed*
        recently — but one case is still legitimately RUNNING with a
        recent, non-stale ``updated_at`` (it was claimed a moment ago). The
        run must be left entirely alone: no case failed, no status change,
        no recovery counted."""
        run = EvaluationRunFactory(status=EvaluationRunStatus.RUNNING, total_cases=2)
        stale_snapshot = EvaluationCaseSnapshotFactory(run=run, sequence=0, case_key="case-0")
        done = EvaluationResultFactory(
            run=run,
            case_snapshot=stale_snapshot,
            status=EvaluationResultStatus.SUCCEEDED,
            passed=True,
        )
        live_snapshot = EvaluationCaseSnapshotFactory(run=run, sequence=1, case_key="case-1")
        live = EvaluationResultFactory(
            run=run, case_snapshot=live_snapshot, status=EvaluationResultStatus.RUNNING
        )
        # The run row itself hasn't been touched since long before either
        # case's own state (a realistic gap: the run was claimed once, then
        # cases dispatched and picked up independently).
        EvaluationRun.objects.filter(pk=run.pk).update(
            completed_cases=1, passed_cases=1, failed_cases=0
        )
        _age_run(run, 10_000)
        # `done` and `live` keep their real (recent) updated_at — this is
        # the point of the scenario.

        recovered = recover_stuck_evaluation_runs()

        run.refresh_from_db()
        done.refresh_from_db()
        live.refresh_from_db()
        assert recovered == 0
        assert run.status == EvaluationRunStatus.RUNNING
        assert live.status == EvaluationResultStatus.RUNNING
        assert live.failure_code == ""
        assert done.status == EvaluationResultStatus.SUCCEEDED

    def test_stale_parent_with_one_actively_running_non_stale_case_is_not_recovered(self):
        """Matrix C: a single-case run whose only case is still genuinely
        RUNNING (recent updated_at) even though the run row is old (its
        updated_at was only ever set once, at claim time)."""
        run = EvaluationRunFactory(status=EvaluationRunStatus.RUNNING, total_cases=1)
        snapshot = EvaluationCaseSnapshotFactory(run=run, sequence=0, case_key="case-0")
        result = EvaluationResultFactory(
            run=run, case_snapshot=snapshot, status=EvaluationResultStatus.RUNNING
        )
        _age_run(run, 10_000)
        # `result.updated_at` stays recent (just claimed).

        recovered = recover_stuck_evaluation_runs()

        run.refresh_from_db()
        result.refresh_from_db()
        assert recovered == 0
        assert run.status == EvaluationRunStatus.RUNNING
        assert result.status == EvaluationResultStatus.RUNNING

    def test_stale_parent_with_all_children_stale_is_recovered(self):
        """Matrix D: every case is genuinely stale (crashed worker) — this
        is the ordinary recovery path, re-asserted here alongside the new
        live-progress carve-out to prove the fix didn't disable it."""
        run, (a, b) = _make_stuck_run(total_cases=2)

        recovered = recover_stuck_evaluation_runs()

        run.refresh_from_db()
        a.refresh_from_db()
        b.refresh_from_db()
        assert recovered == 1
        assert a.status == EvaluationResultStatus.FAILED
        assert b.status == EvaluationResultStatus.FAILED
        assert run.status == EvaluationRunStatus.FAILED

    def test_run_touched_after_batch_query_wins_the_race(self):
        """Sibling to the status-changed race above: the run's own
        ``updated_at`` advanced (a case completed, touching the parent row)
        between the sweep's batch query and this row's own lock. The
        per-row re-check on ``updated_at`` must catch this even though the
        status is still RUNNING."""
        run = EvaluationRunFactory(status=EvaluationRunStatus.RUNNING, total_cases=1)
        cutoff = timezone.now() - timedelta(seconds=3600)
        # The run row is fresh (just created) — never aged — simulating a
        # concurrent case completion having just touched it.

        recovered = _recover_one_stuck_run(run.pk, cutoff=cutoff, now=timezone.now())

        run.refresh_from_db()
        assert recovered is False
        assert run.status == EvaluationRunStatus.RUNNING

    def test_status_changed_after_batch_query_wins_the_race(self):
        """Phase 16 Checkpoint 4 (Part I, high-risk coverage): the run
        reached a terminal status (e.g. a concurrent cancel or genuine
        finalize) between the sweep's batch query and this row's own lock —
        the per-row re-check must be a no-op, never overwrite the real
        terminal outcome."""
        run, (result,) = _make_stuck_run(total_cases=1)
        cutoff = timezone.now() - timedelta(seconds=3600)
        EvaluationRun.objects.filter(pk=run.pk).update(status=EvaluationRunStatus.CANCELLED)

        recovered = _recover_one_stuck_run(run.pk, cutoff=cutoff, now=timezone.now())

        run.refresh_from_db()
        result.refresh_from_db()
        assert recovered is False
        assert run.status == EvaluationRunStatus.CANCELLED
        assert result.status == EvaluationResultStatus.RUNNING

    def test_recovery_race_favors_progress_that_lands_before_the_lock(self):
        """Matrix G: simulates the sweep's batch query selecting a run as a
        stale candidate, then — before the per-row lock is acquired — the
        still-alive worker claims/updates its running case. The row must be
        left alone."""
        run = EvaluationRunFactory(status=EvaluationRunStatus.RUNNING, total_cases=1)
        snapshot = EvaluationCaseSnapshotFactory(run=run, sequence=0, case_key="case-0")
        result = EvaluationResultFactory(
            run=run, case_snapshot=snapshot, status=EvaluationResultStatus.RUNNING
        )
        _age_run(run, 10_000)
        cutoff = timezone.now() - timedelta(seconds=3600)

        # The worker makes real progress on its case right before the
        # per-row lock would be acquired — result.updated_at advances past
        # the cutoff that was computed for this sweep.
        result.save(update_fields=["updated_at"])

        recovered = _recover_one_stuck_run(run.pk, cutoff=cutoff, now=timezone.now())

        run.refresh_from_db()
        result.refresh_from_db()
        assert recovered is False
        assert run.status == EvaluationRunStatus.RUNNING
        assert result.status == EvaluationResultStatus.RUNNING

    def test_recovered_run_cannot_be_regressed_by_a_late_finalize(self):
        """Matrix H: once a run has been recovered (failed), a crashed
        worker's case finally reaching a terminal write (redelivered task,
        or a late provider response) must not regress the run's own
        already-terminal state. ``finalize_evaluation_run`` only ever
        transitions a currently-RUNNING run, so this is a no-op by
        construction — asserted explicitly here as a regression guard."""
        from evaluations.services import finalize_evaluation_run

        run, (result,) = _make_stuck_run(total_cases=1)
        recover_stuck_evaluation_runs()
        run.refresh_from_db()
        assert run.status == EvaluationRunStatus.FAILED

        outcome = finalize_evaluation_run(run.pk)

        run.refresh_from_db()
        result.refresh_from_db()
        assert outcome is None
        assert run.status == EvaluationRunStatus.FAILED
        assert result.status == EvaluationResultStatus.FAILED
        assert run.failed_cases == 1

    def test_recovery_is_visible_via_the_stuck_run_recovery_metric(self):
        """Phase 16 Checkpoint 3 (Part E): recovery previously only emitted
        a structured log line, invisible to a metrics dashboard/alert."""
        from prometheus_client.parser import text_string_to_metric_families

        from observability.metrics import render_metrics

        def _count():
            body = render_metrics().decode("utf-8")
            return sum(
                s.value
                for family in text_string_to_metric_families(body)
                for s in family.samples
                if s.name == "supportpilot_stuck_run_recoveries_total"
                and s.labels.get("domain") == "evaluation"
            )

        before = _count()
        _make_stuck_run(total_cases=1)

        recover_stuck_evaluation_runs()

        assert _count() == before + 1

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
