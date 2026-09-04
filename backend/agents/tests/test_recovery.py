"""Stuck-worker recovery for ``AgentRun`` (Phase 16 Checkpoint 2 Part C).

Timestamps are controlled directly (``queryset.update(updated_at=...)``
bypasses ``auto_now`` the same way a real stale row would have been left by
a crashed worker) rather than sleeping in real time, per the checkpoint's
"do not wait in real time; control timestamps" instruction.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from agents.models import AgentRun, AgentRunStatus, AgentStep, AgentStepType
from agents.recovery import _recover_one_stuck_run, recover_stuck_agent_runs
from agents.services import _fail_run
from tools.models import ToolExecutionStatus
from tools.tests.factories import ToolExecutionFactory

from .factories import AgentRunFactory

pytestmark = pytest.mark.django_db


def _age(run: AgentRun, seconds: int) -> None:
    """Backdate ``updated_at`` the way a genuinely stalled row would be
    found — via a plain ``UPDATE``, never ``save()`` (which would refresh
    ``auto_now`` right back to "now")."""
    AgentRun.objects.filter(pk=run.pk).update(
        updated_at=timezone.now() - timedelta(seconds=seconds)
    )


class TestRecoverStuckAgentRuns:
    def test_not_stale_running_run_is_untouched(self):
        run = AgentRunFactory(status=AgentRunStatus.RUNNING)
        _age(run, seconds=1)  # well under the default 3600s threshold

        recovered = recover_stuck_agent_runs()

        run.refresh_from_db()
        assert recovered == 0
        assert run.status == AgentRunStatus.RUNNING
        assert run.failure_code == ""

    def test_healthy_worker_at_the_theoretical_worst_case_duration_is_not_recovered(self):
        """Phase 16 Checkpoint 2A section 13: ``AgentRun.updated_at`` is
        frozen at claim time for a run's entire real execution — it is
        *not* refreshed by intermediate steps (see
        ``agents/services.py``'s save() call sites). A legitimately
        slow-but-alive run can therefore look exactly this stale purely by
        still being correctly mid-execution. The worst-case duration such a
        healthy run can ever legitimately take is bounded by
        ``AgentVersion``'s own serializer ceilings —
        ``wall_time_limit_seconds<=600`` plus one trailing
        ``provider_timeout_seconds<=300`` call already in flight when that
        ceiling trips (``agents/runtime/budgets.py`` only re-checks
        wall-time *before* starting another call) — i.e. 900s. This proves
        the default stale threshold (validated in settings.py to be >=1800s)
        comfortably clears that real worst case, not just an arbitrary
        round number."""
        run = AgentRunFactory(status=AgentRunStatus.RUNNING)
        _age(run, seconds=900)  # the derived worst-case legitimate duration

        recovered = recover_stuck_agent_runs()

        run.refresh_from_db()
        assert recovered == 0
        assert run.status == AgentRunStatus.RUNNING

    def test_stale_running_run_is_recovered(self):
        run = AgentRunFactory(status=AgentRunStatus.RUNNING)
        _age(run, seconds=10_000)

        recovered = recover_stuck_agent_runs()

        run.refresh_from_db()
        assert recovered == 1
        assert run.status == AgentRunStatus.FAILED
        assert run.failure_code == "stuck_worker_recovered"
        assert run.completed_at is not None
        assert AgentStep.objects.filter(run=run, step_type=AgentStepType.RUN_FAILED).exists()

    @pytest.mark.parametrize(
        "status",
        [
            AgentRunStatus.SUCCEEDED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
            AgentRunStatus.BUDGET_EXCEEDED,
            AgentRunStatus.HANDED_OFF,
            AgentRunStatus.PENDING,
            AgentRunStatus.WAITING_FOR_APPROVAL,
        ],
    )
    def test_only_running_status_is_ever_a_recovery_candidate(self, status):
        run = AgentRunFactory(status=status)
        _age(run, seconds=10_000)

        recovered = recover_stuck_agent_runs()

        run.refresh_from_db()
        assert recovered == 0
        assert run.status == status

    def test_recovery_invoked_twice_is_idempotent(self):
        run = AgentRunFactory(status=AgentRunStatus.RUNNING)
        _age(run, seconds=10_000)

        first = recover_stuck_agent_runs()
        second = recover_stuck_agent_runs()

        run.refresh_from_db()
        assert first == 1
        assert second == 0
        assert run.status == AgentRunStatus.FAILED
        assert AgentStep.objects.filter(run=run, step_type=AgentStepType.RUN_FAILED).count() == 1

    def test_active_worker_progress_after_batch_query_wins_the_race(self):
        """Simulates the exact race in section 11: the sweep's batch query
        selects a candidate id, then — before the per-row lock is acquired —
        the "still alive" worker writes to the row again. The row must be
        left alone: the current owner's result wins."""
        run = AgentRunFactory(status=AgentRunStatus.RUNNING)
        _age(run, seconds=10_000)
        cutoff = timezone.now() - timedelta(seconds=900)

        # The worker "wakes up" and makes real progress right before the
        # per-row lock would be acquired.
        run.step_count = 1
        run.save(update_fields=["step_count", "updated_at"])

        recovered = _recover_one_stuck_run(run.id, cutoff=cutoff, now=timezone.now())

        run.refresh_from_db()
        assert recovered is False
        assert run.status == AgentRunStatus.RUNNING

    def test_old_worker_cannot_regress_a_recovered_run(self):
        """Once recovered, the row is terminal — a later completion attempt
        from the crashed worker (finally reaching the network, or a
        redelivered task) must be rejected by the existing terminal-status
        guard in ``agents.services._fail_run``/``_complete_run``, not
        silently overwrite the recovery outcome."""
        run = AgentRunFactory(status=AgentRunStatus.RUNNING)
        _age(run, seconds=10_000)
        recover_stuck_agent_runs()
        run.refresh_from_db()
        assert run.status == AgentRunStatus.FAILED

        # The "old worker" finally finalizes — this must no-op, not regress
        # the row back to a different terminal outcome.
        result = _fail_run(run, code="late_provider_error", message="late failure")

        run.refresh_from_db()
        assert run.status == AgentRunStatus.FAILED
        assert run.failure_code == "stuck_worker_recovered"
        assert result.failure_code == "stuck_worker_recovered"

    def test_in_flight_tool_execution_is_failed_alongside_the_run(self):
        run = AgentRunFactory(status=AgentRunStatus.RUNNING)
        execution = ToolExecutionFactory(agent_run=run, status=ToolExecutionStatus.RUNNING)
        _age(run, seconds=10_000)

        recover_stuck_agent_runs()

        execution.refresh_from_db()
        assert execution.status == ToolExecutionStatus.FAILED
        assert execution.error_code == "stuck_worker_recovered"

    def test_completed_tool_execution_is_not_clobbered(self):
        """A tool execution that already finished before the crash (only
        the run's own finalization step was lost) must be left exactly as
        it is — recovery only ever fails still in-flight children."""
        run = AgentRunFactory(status=AgentRunStatus.RUNNING)
        execution = ToolExecutionFactory(
            agent_run=run,
            status=ToolExecutionStatus.SUCCEEDED,
            error_code="",
        )
        _age(run, seconds=10_000)

        recover_stuck_agent_runs()

        execution.refresh_from_db()
        assert execution.status == ToolExecutionStatus.SUCCEEDED
        assert execution.error_code == ""

    def test_batch_size_bounds_a_single_sweep(self):
        runs = [AgentRunFactory(status=AgentRunStatus.RUNNING) for _ in range(3)]
        for run in runs:
            _age(run, seconds=10_000)

        recovered = recover_stuck_agent_runs(batch_size=2)

        assert recovered == 2
        statuses = set(
            AgentRun.objects.filter(pk__in=[r.pk for r in runs]).values_list("status", flat=True)
        )
        assert statuses == {AgentRunStatus.RUNNING, AgentRunStatus.FAILED}
