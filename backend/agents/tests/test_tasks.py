from datetime import timedelta

import pytest
from django.utils import timezone

from agents.models import AgentRun, AgentRunStatus
from agents.providers.fake import DeterministicFakeLLMProvider, FakeLLMScenario
from agents.tasks import execute_agent_run_task, recover_stuck_agent_runs_task

from .factories import AgentRunFactory


@pytest.mark.django_db
class TestExecuteAgentRunTask:
    def test_task_calls_the_service_and_returns_the_final_status(self, monkeypatch):
        provider = DeterministicFakeLLMProvider(FakeLLMScenario(response="answer"))
        monkeypatch.setattr("agents.services.get_llm_provider", lambda: provider)
        run = AgentRunFactory()

        result = execute_agent_run_task.apply(args=[str(run.id)]).result

        assert result == AgentRunStatus.SUCCEEDED
        run.refresh_from_db()
        assert run.status == AgentRunStatus.SUCCEEDED

    def test_task_does_not_duplicate_runtime_logic(self):
        # The task body must be a thin call into the service layer — no
        # provider/graph imports of its own.
        import inspect

        source = inspect.getsource(execute_agent_run_task)
        assert "run_graph" not in source
        assert "LLMProvider" not in source


@pytest.mark.django_db
class TestRecoverStuckAgentRunsTask:
    """Celery Beat wrapper (Phase 17) — thin delegation only, see
    ``agents/tests/test_recovery.py`` for the actual recovery logic
    coverage."""

    def test_task_delegates_to_the_recovery_sweep(self):
        run = AgentRunFactory(status=AgentRunStatus.RUNNING)
        AgentRun.objects.filter(pk=run.pk).update(
            updated_at=timezone.now() - timedelta(seconds=3601)
        )

        recovered = recover_stuck_agent_runs_task.apply().result

        assert recovered == 1
        run.refresh_from_db()
        assert run.status == AgentRunStatus.FAILED
        assert run.failure_code == "stuck_worker_recovered"

    def test_task_is_a_thin_wrapper_with_no_recovery_logic_of_its_own(self):
        import inspect

        source = inspect.getsource(recover_stuck_agent_runs_task)
        assert "select_for_update" not in source
        assert "AgentRunStatus.FAILED" not in source
