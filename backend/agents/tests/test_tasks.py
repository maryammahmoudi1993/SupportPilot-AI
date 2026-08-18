import pytest

from agents.models import AgentRunStatus
from agents.providers.fake import DeterministicFakeLLMProvider, FakeLLMScenario
from agents.tasks import execute_agent_run_task

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
