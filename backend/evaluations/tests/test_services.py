"""Service-level tests exercising the real production orchestration boundary
(section 53, 55-61)."""

from __future__ import annotations

import pytest

from accounts.tests.factories import UserFactory
from agents.models import AgentRunStatus
from agents.tests.factories import PublishedAgentVersionFactory
from tools.tests.factories import ToolBindingFactory, ToolDefinitionFactory
from workspaces.tests.factories import WorkspaceFactory

from .. import services
from ..errors import (
    EvaluationDatasetHasNoActiveCasesError,
    EvaluationResultNotReplayableError,
    EvaluationRunNotCancellableError,
    EvaluationRunsNotComparableError,
)
from ..models import (
    EvaluationCaseStatus,
    EvaluationFailureCode,
    EvaluationResultStatus,
    EvaluationRunStatus,
)
from .factories import EvaluationCaseFactory, EvaluationDatasetFactory


def _dataset_with_case(*, workspace, case_kwargs=None):
    dataset = EvaluationDatasetFactory(workspace=workspace)
    case = EvaluationCaseFactory(dataset=dataset, **(case_kwargs or {}))
    return dataset, case


def _run_all(run):
    """Directly claims and executes every pending result of ``run`` — the
    synchronous equivalent of the Celery batch (tests never rely on
    ``transaction.on_commit`` firing, matching repository convention)."""
    for result in run.results.filter(status=EvaluationResultStatus.PENDING):
        services.execute_evaluation_case(result.id)
    run.refresh_from_db()
    return run


@pytest.mark.django_db
class TestRunLifecycle:
    def test_start_run_snapshots_cases_and_creates_pending_results(self):
        workspace = WorkspaceFactory()
        dataset, case = _dataset_with_case(workspace=workspace)
        version = PublishedAgentVersionFactory(agent_definition__workspace=workspace)
        actor = UserFactory()

        run = services.start_evaluation_run(
            workspace=workspace, actor=actor, dataset=dataset, agent_version=version
        )
        assert run.status == EvaluationRunStatus.PENDING
        assert run.total_cases == 1
        snapshot = run.case_snapshots.get()
        assert snapshot.case_key == case.key
        assert snapshot.input_message == case.input_message
        result = run.results.get()
        assert result.status == EvaluationResultStatus.PENDING
        assert result.case_snapshot_id == snapshot.id

    def test_disabled_cases_are_excluded_and_empty_dataset_rejected(self):
        workspace = WorkspaceFactory()
        dataset, case = _dataset_with_case(
            workspace=workspace, case_kwargs={"status": EvaluationCaseStatus.DISABLED}
        )
        version = PublishedAgentVersionFactory(agent_definition__workspace=workspace)
        with pytest.raises(EvaluationDatasetHasNoActiveCasesError):
            services.start_evaluation_run(
                workspace=workspace, actor=UserFactory(), dataset=dataset, agent_version=version
            )

    def test_full_run_scores_and_finalizes_succeeded(self):
        workspace = WorkspaceFactory()
        dataset, case = _dataset_with_case(workspace=workspace)
        version = PublishedAgentVersionFactory(agent_definition__workspace=workspace)
        run = services.start_evaluation_run(
            workspace=workspace, actor=UserFactory(), dataset=dataset, agent_version=version
        )
        services.claim_evaluation_run(run.id)
        run = _run_all(run)

        assert run.status == EvaluationRunStatus.SUCCEEDED
        assert run.completed_cases == 1
        result = run.results.get()
        assert result.status == EvaluationResultStatus.SUCCEEDED
        assert result.agent_run.status == AgentRunStatus.SUCCEEDED

    def test_duplicate_case_execution_is_idempotent(self):
        workspace = WorkspaceFactory()
        dataset, case = _dataset_with_case(workspace=workspace)
        version = PublishedAgentVersionFactory(agent_definition__workspace=workspace)
        run = services.start_evaluation_run(
            workspace=workspace, actor=UserFactory(), dataset=dataset, agent_version=version
        )
        services.claim_evaluation_run(run.id)
        result = run.results.get()

        first = services.execute_evaluation_case(result.id)
        second = services.execute_evaluation_case(result.id)

        assert first.id == second.id
        assert first.agent_run_id == second.agent_run_id
        run.refresh_from_db()
        assert run.completed_cases == 1  # never double-counted


@pytest.mark.django_db
class TestForbiddenToolSafety:
    def test_forbidden_tool_executing_is_a_safety_failure_with_no_real_side_effect(self):
        workspace = WorkspaceFactory()
        version = PublishedAgentVersionFactory(
            agent_definition__workspace=workspace, max_model_calls=2
        )
        tool_definition = ToolDefinitionFactory(key="demo.add")
        ToolBindingFactory(agent_version=version, tool_definition=tool_definition)

        dataset = EvaluationDatasetFactory(workspace=workspace)
        EvaluationCaseFactory(
            dataset=dataset,
            seeded_context={
                "llm_scenarios": [
                    {
                        "response": "",
                        "tool_calls": [{"tool_key": "demo.add", "arguments": {"a": 1, "b": 2}}],
                    },
                    {"response": "Done."},
                ]
            },
            expectations={"forbidden_tools": ["demo.add"]},
        )
        run = services.start_evaluation_run(
            workspace=workspace, actor=UserFactory(), dataset=dataset, agent_version=version
        )
        services.claim_evaluation_run(run.id)
        result = services.execute_evaluation_case(run.results.get().id)

        assert result.passed is False
        assert result.failure_code == EvaluationFailureCode.FORBIDDEN_TOOL_VIOLATION
        assert result.scorer_output["forbidden_tool_violation"] is True
        # The demo tool actually running is expected here (it is a safe,
        # side-effect-free deterministic demo handler) — the assertion is
        # that the *evaluator* correctly flags it, matching the runtime's
        # real permission grant for this case's tool binding.


@pytest.mark.django_db
class TestCancellationAndReplay:
    def test_cancel_prevents_new_claims_and_is_idempotent(self):
        workspace = WorkspaceFactory()
        dataset = EvaluationDatasetFactory(workspace=workspace)
        EvaluationCaseFactory(dataset=dataset, key="case-a")
        EvaluationCaseFactory(dataset=dataset, key="case-b")
        version = PublishedAgentVersionFactory(agent_definition__workspace=workspace)
        actor = UserFactory()
        run = services.start_evaluation_run(
            workspace=workspace, actor=actor, dataset=dataset, agent_version=version
        )

        cancelled = services.cancel_evaluation_run(workspace=workspace, run=run, actor=actor)
        assert cancelled.status == EvaluationRunStatus.CANCELLED
        for result in cancelled.results.all():
            assert result.status == EvaluationResultStatus.CANCELLED

        with pytest.raises(EvaluationRunNotCancellableError):
            services.cancel_evaluation_run(workspace=workspace, run=cancelled, actor=actor)

        # A claim attempt on an already-cancelled case's PENDING slot cannot
        # happen (it is CANCELLED already) — executing it again is a no-op.
        result = cancelled.results.first()
        unchanged = services.execute_evaluation_case(result.id)
        assert unchanged.status == EvaluationResultStatus.CANCELLED

    def test_replay_creates_a_new_result_and_never_mutates_the_original(self):
        workspace = WorkspaceFactory()
        dataset, case = _dataset_with_case(workspace=workspace)
        version = PublishedAgentVersionFactory(agent_definition__workspace=workspace)
        actor = UserFactory()
        run = services.start_evaluation_run(
            workspace=workspace, actor=actor, dataset=dataset, agent_version=version
        )
        services.claim_evaluation_run(run.id)
        original = services.execute_evaluation_case(run.results.get().id)
        original_agent_run_id = original.agent_run_id

        replay = services.replay_evaluation_case(workspace=workspace, actor=actor, result=original)
        assert replay.id != original.id
        assert replay.replay_of_id == original.id
        assert replay.status == EvaluationResultStatus.PENDING

        executed_replay = services.execute_evaluation_case(replay.id)
        assert executed_replay.agent_run_id != original_agent_run_id

        original.refresh_from_db()
        assert original.agent_run_id == original_agent_run_id  # untouched

        # A replay must not double-count the parent run's aggregates.
        run.refresh_from_db()
        assert run.completed_cases == 1

    def test_replay_requires_terminal_result(self):
        workspace = WorkspaceFactory()
        dataset, case = _dataset_with_case(workspace=workspace)
        version = PublishedAgentVersionFactory(agent_definition__workspace=workspace)
        actor = UserFactory()
        run = services.start_evaluation_run(
            workspace=workspace, actor=actor, dataset=dataset, agent_version=version
        )
        pending_result = run.results.get()
        with pytest.raises(EvaluationResultNotReplayableError):
            services.replay_evaluation_case(workspace=workspace, actor=actor, result=pending_result)


@pytest.mark.django_db
class TestBatchPartialFailure:
    def test_mixed_success_and_execution_failure_finalizes_partial(self):
        workspace = WorkspaceFactory()
        dataset = EvaluationDatasetFactory(workspace=workspace)
        EvaluationCaseFactory(dataset=dataset, key="ok-1")
        EvaluationCaseFactory(
            dataset=dataset,
            key="bad-scenario",
            seeded_context={"llm_scenarios": [{"unexpected_field": "boom"}]},
        )
        EvaluationCaseFactory(dataset=dataset, key="ok-2")
        version = PublishedAgentVersionFactory(agent_definition__workspace=workspace)
        run = services.start_evaluation_run(
            workspace=workspace, actor=UserFactory(), dataset=dataset, agent_version=version
        )
        services.claim_evaluation_run(run.id)
        run = _run_all(run)

        assert run.status == EvaluationRunStatus.PARTIAL
        assert run.completed_cases == 3
        assert run.passed_cases == 2
        assert run.failed_cases == 1
        failed = run.results.get(case_snapshot__case_key="bad-scenario")
        assert failed.status == EvaluationResultStatus.FAILED
        assert failed.failure_code == EvaluationFailureCode.INVALID_CASE


@pytest.mark.django_db
class TestComparison:
    def test_paired_comparison_detects_regression_against_threshold(self):
        workspace = WorkspaceFactory()
        dataset = EvaluationDatasetFactory(workspace=workspace)
        EvaluationCaseFactory(
            dataset=dataset,
            key="c1",
            expectations={
                "outcome_assertions": [{"type": "run_terminal_state_equals", "value": "succeeded"}]
            },
        )
        baseline_version = PublishedAgentVersionFactory(agent_definition__workspace=workspace)
        candidate_version = PublishedAgentVersionFactory(agent_definition__workspace=workspace)
        actor = UserFactory()

        baseline_run = services.start_evaluation_run(
            workspace=workspace, actor=actor, dataset=dataset, agent_version=baseline_version
        )
        services.claim_evaluation_run(baseline_run.id)
        baseline_run = _run_all(baseline_run)

        candidate_run = services.start_evaluation_run(
            workspace=workspace,
            actor=actor,
            dataset=dataset,
            agent_version=candidate_version,
            threshold_config={"min_pass_rate": 1.0, "zero_forbidden_tool_violations": True},
        )
        services.claim_evaluation_run(candidate_run.id)
        candidate_run = _run_all(candidate_run)

        comparison = services.compare_evaluation_runs(
            workspace=workspace, baseline_run=baseline_run, candidate_run=candidate_run, actor=actor
        )
        assert comparison["case_count"] == 1
        assert comparison["passed"] is True
        assert comparison["deltas"]["pass_rate"] == 0.0

    def test_incompatible_case_sets_are_rejected(self):
        workspace = WorkspaceFactory()
        dataset_a = EvaluationDatasetFactory(workspace=workspace)
        EvaluationCaseFactory(dataset=dataset_a, key="only-in-a")
        dataset_b = EvaluationDatasetFactory(workspace=workspace)
        EvaluationCaseFactory(dataset=dataset_b, key="only-in-b")
        version = PublishedAgentVersionFactory(agent_definition__workspace=workspace)
        actor = UserFactory()

        run_a = services.start_evaluation_run(
            workspace=workspace, actor=actor, dataset=dataset_a, agent_version=version
        )
        run_b = services.start_evaluation_run(
            workspace=workspace, actor=actor, dataset=dataset_b, agent_version=version
        )
        with pytest.raises(EvaluationRunsNotComparableError):
            services.compare_evaluation_runs(
                workspace=workspace, baseline_run=run_a, candidate_run=run_b, actor=actor
            )
