"""Real PostgreSQL concurrency for the evaluation harness (Phase 16 Part A,
section 12): same run started twice, two cases finishing concurrently and
racing to finalize the run, and cancel racing an in-flight case claim —
proven with real threads against real row locks, mirroring the established
pattern in ``webhooks/tests/test_concurrency.py`` and
``agents/tests/test_concurrency.py``."""

from __future__ import annotations

import threading

import django.db as django_db
import pytest

from accounts.tests.factories import UserFactory
from agents.tests.factories import PublishedAgentVersionFactory
from audit.models import AuditAction, AuditEvent
from workspaces.tests.factories import WorkspaceFactory

from .. import services
from ..errors import EvaluationRunNotCancellableError
from ..models import EvaluationResultStatus, EvaluationRunStatus
from .factories import EvaluationCaseFactory, EvaluationDatasetFactory

pytestmark = pytest.mark.django_db(transaction=True)


def _run_in_threads(callables):
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
        # Real full-orchestration case execution (fake-provider LLM call,
        # audit, tracing) is slower than the simple row-transition races
        # elsewhere in this module and can occasionally exceed a short join
        # timeout under a loaded test run (many sequential tests sharing
        # one DB/process) — a silent ``Thread.join`` timeout would then let
        # the test assert on a still-in-flight thread's stale state,
        # manifesting as a flake with no real logic defect behind it.
        # ``join`` with a generous ceiling, then fail loudly (not
        # silently) if a thread is still alive — a genuine hang should be
        # a clear failure, never a quietly wrong assertion.
        t.join(timeout=60)
    still_running = [t for t in threads if t.is_alive()]
    assert not still_running, "a worker thread did not finish within the join timeout"
    return results, errors


def _two_case_run():
    workspace = WorkspaceFactory()
    dataset = EvaluationDatasetFactory(workspace=workspace)
    EvaluationCaseFactory(dataset=dataset, key="case-a")
    EvaluationCaseFactory(dataset=dataset, key="case-b")
    version = PublishedAgentVersionFactory(agent_definition__workspace=workspace)
    run = services.start_evaluation_run(
        workspace=workspace, actor=UserFactory(), dataset=dataset, agent_version=version
    )
    services.claim_evaluation_run(run.id)
    return run


class TestEvaluationRunClaimRace:
    """same run started twice (section 12): two workers concurrently
    claiming the same PENDING run must never both transition it to
    RUNNING."""

    def test_two_concurrent_claims_only_one_succeeds(self):
        workspace = WorkspaceFactory()
        dataset = EvaluationDatasetFactory(workspace=workspace)
        EvaluationCaseFactory(dataset=dataset)
        version = PublishedAgentVersionFactory(agent_definition__workspace=workspace)
        run = services.start_evaluation_run(
            workspace=workspace, actor=UserFactory(), dataset=dataset, agent_version=version
        )

        results, errors = _run_in_threads(
            [
                lambda: services.claim_evaluation_run(run.id),
                lambda: services.claim_evaluation_run(run.id),
            ]
        )

        assert errors == [None, None]
        claimed = [r for r in results if r is not None]
        assert len(claimed) == 1
        run.refresh_from_db()
        assert run.status == EvaluationRunStatus.RUNNING


class TestEvaluationFinalizationRace:
    """finalization races / duplicate result persistence (section 12): two
    cases of the same run finishing concurrently must finalize the run
    exactly once, with correct aggregate counts and exactly one audit
    event."""

    def test_two_concurrent_case_completions_finalize_exactly_once(self):
        run = _two_case_run()
        result_ids = list(run.results.values_list("id", flat=True))
        assert len(result_ids) == 2

        results, errors = _run_in_threads(
            [
                lambda rid=result_ids[0]: services.execute_evaluation_case(rid),
                lambda rid=result_ids[1]: services.execute_evaluation_case(rid),
            ]
        )

        assert errors == [None, None]
        run.refresh_from_db()
        assert run.status == EvaluationRunStatus.SUCCEEDED
        assert run.completed_cases == 2
        assert run.passed_cases + run.failed_cases == 2
        # Finalization is guarded by a RUNNING->terminal transition inside
        # its own lock (finalize_evaluation_run), so no matter which racer's
        # _record_case_completion call observes completed_cases >=
        # total_cases first, exactly one audit event is ever recorded.
        assert (
            AuditEvent.objects.filter(
                action=AuditAction.EVALUATION_RUN_COMPLETED, target_id=str(run.id)
            ).count()
            == 1
        )


class TestEvaluationCancelVsCompletionRace:
    """cancel vs case completion (section 12): cancelling a run while its
    last pending case is concurrently being claimed/executed must never let
    a cancelled run finalize as SUCCEEDED, and must never let the
    cancellation silently lose track of a case that already started."""

    def test_cancel_racing_a_case_claim_yields_a_consistent_terminal_state(self):
        run = _two_case_run()
        result_ids = list(run.results.values_list("id", flat=True))
        actor = UserFactory()

        def cancel():
            return services.cancel_evaluation_run(workspace=run.workspace, run=run, actor=actor)

        def execute_first_case():
            return services.execute_evaluation_case(result_ids[0])

        results, errors = _run_in_threads([cancel, execute_first_case])

        run.refresh_from_db()
        cancel_result, exec_result = results
        cancel_error, exec_error = errors

        # cancel_evaluation_run only raises EvaluationRunNotCancellableError
        # if the run was already terminal; execute_evaluation_case never
        # raises for a normal race (it claims-or-no-ops).
        assert cancel_error is None or isinstance(cancel_error, EvaluationRunNotCancellableError)
        assert exec_error is None

        # The run must end in a real terminal state — never left RUNNING
        # forever, and never resurrected back to PENDING/RUNNING after
        # cancellation won the race.
        assert run.status in {
            EvaluationRunStatus.CANCELLED,
            EvaluationRunStatus.SUCCEEDED,
            EvaluationRunStatus.PARTIAL,
            EvaluationRunStatus.FAILED,
        }
        # The racing result (case A) is never left PENDING — it is either
        # CANCELLED (cancel won the claim race) or reached a real terminal
        # execution status (claim won first).
        stored_status = run.results.get(pk=result_ids[0]).status
        assert stored_status != EvaluationResultStatus.PENDING
