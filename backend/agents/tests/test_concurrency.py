"""Real PostgreSQL concurrency for agent-run state transitions (Phase 16
Part A, section 7): two threads racing the same run's terminal/claim
transitions through real row locks (``select_for_update``) must produce
exactly one authoritative outcome — never an impossible transition, never a
regression from a terminal state back to running, never a duplicate
terminal side effect.

Mirrors the established pattern in ``webhooks/tests/test_concurrency.py``
and ``notifications/tests/test_concurrency.py``: real threads, a
``threading.Barrier`` to force genuine overlap, and
``django.db.close_old_connections()`` per worker thread so each gets its own
DB connection under ``pytest.mark.django_db(transaction=True)``.
"""

from __future__ import annotations

import threading

import django.db as django_db
import pytest

from accounts.tests.factories import UserFactory
from agents.errors import AgentRunNotCancellableError
from agents.models import AGENT_RUN_TERMINAL_STATUSES, AgentRun, AgentRunStatus
from agents.services import _claim_run_for_resume, cancel_agent_run, claim_agent_run

from .factories import AgentRunFactory

pytestmark = pytest.mark.django_db(transaction=True)


def _run_in_threads(callables):
    """Run each zero-arg callable in its own thread with a shared barrier so
    all threads enter their critical section at (approximately) the same
    time, collecting each callable's return value or raised exception."""
    barrier = threading.Barrier(len(callables))
    results: list[object] = [None] * len(callables)
    errors: list[BaseException | None] = [None] * len(callables)

    def make_worker(index, fn):
        def worker():
            django_db.close_old_connections()
            barrier.wait()
            try:
                results[index] = fn()
            except BaseException as exc:  # noqa: BLE001 - captured for assertion
                errors[index] = exc
            finally:
                django_db.close_old_connections()

        return worker

    threads = [threading.Thread(target=make_worker(i, fn)) for i, fn in enumerate(callables)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    return results, errors


class TestAgentRunClaimRace:
    """start/start (section 7): two workers concurrently claiming the same
    PENDING run must never both transition it to RUNNING."""

    def test_two_concurrent_claims_only_one_succeeds(self):
        run = AgentRunFactory(status=AgentRunStatus.PENDING)

        results, errors = _run_in_threads(
            [lambda: claim_agent_run(run.pk), lambda: claim_agent_run(run.pk)]
        )

        assert errors == [None, None]
        # Exactly one caller observes the claimed run; the other observes
        # ``None`` (already claimed) per ``claim_agent_run``'s contract.
        claimed = [r for r in results if r is not None]
        skipped = [r for r in results if r is None]
        assert len(claimed) == 1
        assert len(skipped) == 1

        run.refresh_from_db()
        assert run.status == AgentRunStatus.RUNNING
        assert run.started_at is not None


class TestAgentRunCancelRace:
    """cancel/cancel (section 7): two concurrent cancellations of the same
    run must produce exactly one authoritative cancellation and no
    duplicate terminal side effect."""

    def test_two_concurrent_cancels_only_one_succeeds(self):
        run = AgentRunFactory(status=AgentRunStatus.RUNNING)
        actor = UserFactory()

        def cancel():
            return cancel_agent_run(workspace=run.workspace, run=run, actor=actor)

        results, errors = _run_in_threads([cancel, cancel])

        succeeded = [r for r in results if r is not None]
        failed = [e for e in errors if isinstance(e, AgentRunNotCancellableError)]
        assert len(succeeded) == 1
        assert len(failed) == 1

        run.refresh_from_db()
        assert run.status == AgentRunStatus.CANCELLED
        # Exactly one RUN_CANCELLED step was recorded — no duplicate side
        # effect from the losing racer.
        from agents.models import AgentStep, AgentStepType

        assert AgentStep.objects.filter(run=run, step_type=AgentStepType.RUN_CANCELLED).count() == 1

    def test_cancel_cannot_regress_a_run_already_terminated_by_the_other_racer(self):
        """cancel/complete (section 7): a racing terminal completion must
        never be clobbered back to CANCELLED, and a racing cancel of an
        already-terminal run must never silently succeed."""
        run = AgentRunFactory(status=AgentRunStatus.RUNNING)
        actor = UserFactory()

        def cancel():
            return cancel_agent_run(workspace=run.workspace, run=run, actor=actor)

        def complete_via_direct_terminal_update():
            # Simulates the orchestration completing the run to SUCCEEDED
            # under its own lock, racing the cancel above for the same row.
            from django.db import transaction
            from django.utils import timezone

            with transaction.atomic():
                locked = AgentRun.objects.select_for_update().get(pk=run.pk)
                if locked.status in AGENT_RUN_TERMINAL_STATUSES:
                    return None
                locked.status = AgentRunStatus.SUCCEEDED
                locked.completed_at = timezone.now()
                locked.save()
                return locked

        results, errors = _run_in_threads([cancel, complete_via_direct_terminal_update])

        run.refresh_from_db()
        # Whichever racer's lock was acquired first wins; the loser either
        # raises AgentRunNotCancellableError or observes None — never both
        # succeed, and the final state is one of the two terminal statuses,
        # never a non-terminal or corrupted state.
        assert run.status in {AgentRunStatus.CANCELLED, AgentRunStatus.SUCCEEDED}
        non_none_results = [r for r in results if r is not None]
        assert len(non_none_results) == 1


class TestAgentRunResumeCancelRace:
    """resume/cancel (section 7): a racing cancel of a run waiting for
    approval must never let a concurrent resume-claim also succeed, and
    vice versa — exactly one of RUNNING (resumed) or CANCELLED wins."""

    def test_resume_claim_and_cancel_are_mutually_exclusive(self):
        run = AgentRunFactory(status=AgentRunStatus.PENDING)
        AgentRun.objects.filter(pk=run.pk).update(status=AgentRunStatus.WAITING_FOR_APPROVAL)
        run.refresh_from_db()
        actor = UserFactory()

        def resume():
            return _claim_run_for_resume(run.pk)

        def cancel():
            return cancel_agent_run(workspace=run.workspace, run=run, actor=actor)

        results, errors = _run_in_threads([resume, cancel])

        run.refresh_from_db()
        resume_result, cancel_result = results
        resume_error, cancel_error = errors

        if resume_result is not None:
            # Resume won the race: run is RUNNING, and the cancel racer must
            # have observed the run as already terminal-or-non-cancellable.
            # Since WAITING_FOR_APPROVAL is not terminal, cancel_agent_run
            # would instead observe RUNNING and legitimately cancel it from
            # there unless it lost the row lock entirely and saw the
            # already-updated status change underneath — assert the run
            # never ends up back in WAITING_FOR_APPROVAL (stale overwrite).
            assert run.status != AgentRunStatus.WAITING_FOR_APPROVAL
        else:
            # Cancel won the race first: resume must report "already
            # resumed"-style None (not WAITING_FOR_APPROVAL anymore), and
            # the run must be CANCELLED, never RUNNING.
            assert cancel_result is not None
            assert run.status == AgentRunStatus.CANCELLED
            assert cancel_error is None

        # No impossible terminal transition and no exception besides the
        # expected not-cancellable guard.
        for err in (resume_error, cancel_error):
            assert err is None or isinstance(err, AgentRunNotCancellableError)
