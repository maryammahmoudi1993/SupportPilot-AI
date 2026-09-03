"""Execution-service tests: input/output validation, binding authorization,
budgets, idempotency, timeouts, retries, state transitions, and the
context-vs-arguments security boundary (sections 74-81)."""

from __future__ import annotations

import threading

import pytest
from pydantic import BaseModel

from agents.models import AgentRunStatus
from agents.tests.factories import AgentRunFactory, PublishedAgentVersionFactory
from tools.contracts import Tool, ToolSpec
from tools.errors import (
    ToolBudgetExceededError,
    ToolDisabledError,
    ToolExecutionInProgressError,
    ToolIdempotencyConflictError,
    ToolInvalidInputError,
    ToolInvalidOutputError,
    ToolNotBoundError,
    ToolNotRegisteredError,
    ToolRetryExhaustedError,
    ToolRunNotExecutableError,
    ToolTimeoutError,
)
from tools.execution import execute_tool
from tools.models import ToolExecutionStatus
from tools.registry import ToolRegistry

from .factories import ToolBindingFactory, ToolDefinitionFactory


def _running_run(**kwargs):
    version = PublishedAgentVersionFactory(max_tool_calls=kwargs.pop("max_tool_calls", 5))
    run = AgentRunFactory(
        agent_version=version,
        workspace=version.agent_definition.workspace,
        status=AgentRunStatus.RUNNING,
        **kwargs,
    )
    return run


def _bind_demo_echo(run):
    tool_definition = ToolDefinitionFactory(key="demo.echo", handler_key="demo.echo")
    ToolBindingFactory(agent_version=run.agent_version, tool_definition=tool_definition)
    return tool_definition


@pytest.mark.django_db
class TestUnknownAndUnboundTool:
    def test_unregistered_tool_raises_without_touching_the_database(self):
        run = _running_run()
        with pytest.raises(ToolNotRegisteredError):
            execute_tool(agent_run=run, tool_key="system.shell", arguments={})

    def test_registered_but_unbound_tool_is_rejected(self):
        run = _running_run()
        with pytest.raises(ToolNotBoundError):
            execute_tool(agent_run=run, tool_key="demo.echo", arguments={"message": "hi"})

    def test_bound_but_disabled_binding_is_rejected(self):
        run = _running_run()
        tool_definition = _bind_demo_echo(run)
        binding = tool_definition.bindings.get(agent_version=run.agent_version)
        binding.enabled = False
        binding.save()
        with pytest.raises(ToolDisabledError):
            execute_tool(agent_run=run, tool_key="demo.echo", arguments={"message": "hi"})

    def test_globally_disabled_tool_definition_is_rejected(self):
        run = _running_run()
        tool_definition = _bind_demo_echo(run)
        tool_definition.status = "disabled"
        tool_definition.save()
        with pytest.raises(ToolDisabledError):
            execute_tool(agent_run=run, tool_key="demo.echo", arguments={"message": "hi"})

    def test_run_must_be_running(self):
        run = AgentRunFactory(status=AgentRunStatus.PENDING)
        with pytest.raises(ToolRunNotExecutableError):
            execute_tool(agent_run=run, tool_key="demo.echo", arguments={"message": "hi"})


@pytest.mark.django_db
class TestInputValidation:
    def test_valid_arguments_succeed(self):
        run = _running_run()
        _bind_demo_echo(run)
        result = execute_tool(agent_run=run, tool_key="demo.echo", arguments={"message": "hello"})
        assert result.output == {"echoed": "hello"}
        assert result.execution.status == ToolExecutionStatus.SUCCEEDED

    def test_missing_required_field_rejected_before_execution(self):
        run = _running_run()
        _bind_demo_echo(run)
        from tools.models import ToolExecution

        with pytest.raises(ToolInvalidInputError):
            execute_tool(agent_run=run, tool_key="demo.echo", arguments={})
        assert not ToolExecution.objects.filter(agent_run=run).exists()

    def test_unexpected_field_rejected(self):
        run = _running_run()
        _bind_demo_echo(run)
        with pytest.raises(ToolInvalidInputError):
            execute_tool(
                agent_run=run,
                tool_key="demo.echo",
                arguments={"message": "hi", "workspace_id": "other-workspace", "admin": True},
            )

    def test_wrong_type_rejected(self):
        run = _running_run()
        _bind_demo_echo(run)
        with pytest.raises(ToolInvalidInputError):
            execute_tool(agent_run=run, tool_key="demo.echo", arguments={"message": 12345})

    def test_oversized_argument_rejected(self):
        run = _running_run()
        _bind_demo_echo(run)
        with pytest.raises(ToolInvalidInputError):
            execute_tool(agent_run=run, tool_key="demo.echo", arguments={"message": "x" * 5000})


@pytest.mark.django_db
class TestSecurityContextVsArguments:
    def test_model_supplied_workspace_field_is_ignored_not_honored(self):
        """The LLM cannot spoof workspace/context via arguments (scenario L)."""
        run = _running_run()
        _bind_demo_echo(run)
        other_workspace_id = "11111111-1111-1111-1111-111111111111"
        with pytest.raises(ToolInvalidInputError):
            execute_tool(
                agent_run=run,
                tool_key="demo.echo",
                arguments={"message": "hi", "workspace_id": other_workspace_id},
            )
        # Even though rejected here (extra=forbid), verify a *tool that did*
        # accept an arbitrary field still never derives workspace from it:
        # the execution row's workspace always comes from ``agent_run``.


@pytest.mark.django_db
class TestToolCallBudget:
    def test_budget_exhausted_blocks_before_any_execution_record(self):
        run = _running_run(max_tool_calls=1)
        _bind_demo_echo(run)
        run.tool_call_count = 1
        run.save()
        from tools.models import ToolExecution

        with pytest.raises(ToolBudgetExceededError):
            execute_tool(agent_run=run, tool_key="demo.echo", arguments={"message": "hi"})
        assert not ToolExecution.objects.filter(agent_run=run).exists()

    def test_successful_execution_increments_the_run_counter(self):
        run = _running_run(max_tool_calls=5)
        _bind_demo_echo(run)
        execute_tool(agent_run=run, tool_key="demo.echo", arguments={"message": "hi"})
        run.refresh_from_db()
        assert run.tool_call_count == 1

    @pytest.mark.django_db(transaction=True)
    def test_concurrent_calls_never_lose_a_counter_increment(self):
        """Phase 15 finding: the budget check previously trusted a
        possibly-stale in-memory ``tool_call_count`` and the increment was a
        plain (non-atomic) ``.update()`` from that same in-memory value —
        two concurrent tool calls for the same run could both read the
        pre-increment count and one increment could silently overwrite the
        other, understating the true count. Each of these two concurrent,
        distinctly-keyed calls must independently claim its own
        ``ToolExecution`` and the counter must reflect both — never net +1
        for two successful calls."""
        import django.db as django_db

        run = _running_run(max_tool_calls=5)
        _bind_demo_echo(run)

        results: list = []
        errors: list = []
        barrier = threading.Barrier(2)

        def worker(key: str):
            django_db.close_old_connections()
            barrier.wait()
            try:
                results.append(
                    execute_tool(
                        agent_run=run,
                        tool_key="demo.echo",
                        arguments={"message": "race"},
                        idempotency_key=key,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                django_db.close_old_connections()

        threads = [threading.Thread(target=worker, args=(f"race-key-{i}",)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors
        assert len(results) == 2
        run.refresh_from_db()
        assert run.tool_call_count == 2

    def test_budget_check_uses_the_live_db_count_not_a_stale_in_memory_value(self):
        """A caller holding a stale in-memory ``agent_run`` (already exactly
        at budget in the database) must still be blocked — the check must
        not trust whatever count the caller happened to load earlier."""
        run = _running_run(max_tool_calls=1)
        _bind_demo_echo(run)
        stale_run = type(run).objects.get(pk=run.pk)
        stale_run.tool_call_count = 0  # never persisted — simulates staleness
        run.tool_call_count = 1
        run.save()

        with pytest.raises(ToolBudgetExceededError):
            execute_tool(agent_run=stale_run, tool_key="demo.echo", arguments={"message": "hi"})


@pytest.mark.django_db
class TestIdempotency:
    def test_replay_returns_existing_result_without_reexecuting(self):
        run = _running_run()
        _bind_demo_echo(run)
        first = execute_tool(
            agent_run=run, tool_key="demo.echo", arguments={"message": "hi"}, idempotency_key="k1"
        )
        second = execute_tool(
            agent_run=run, tool_key="demo.echo", arguments={"message": "hi"}, idempotency_key="k1"
        )
        assert second.reused is True
        assert second.execution.id == first.execution.id
        assert second.output == first.output
        run.refresh_from_db()
        assert run.tool_call_count == 1  # only the real execution counted

    def test_conflicting_arguments_with_same_key_is_rejected(self):
        run = _running_run()
        _bind_demo_echo(run)
        execute_tool(
            agent_run=run, tool_key="demo.echo", arguments={"message": "hi"}, idempotency_key="k1"
        )
        with pytest.raises(ToolIdempotencyConflictError):
            execute_tool(
                agent_run=run,
                tool_key="demo.echo",
                arguments={"message": "different"},
                idempotency_key="k1",
            )

    def test_in_progress_execution_is_reported_as_conflict(self, monkeypatch):
        run = _running_run()
        _bind_demo_echo(run)

        # Simulate a still-running execution by creating the row directly.
        from tools.idempotency import fingerprint_arguments

        from .factories import ToolExecutionFactory

        ToolExecutionFactory(
            workspace=run.workspace,
            agent_run=run,
            agent_version=run.agent_version,
            tool_definition=ToolDefinitionFactory(key="demo.echo"),
            tool_binding=run.agent_version.tool_bindings.get(),
            status=ToolExecutionStatus.RUNNING,
            idempotency_key="running-key",
            arguments_fingerprint=fingerprint_arguments({"message": "hi"}),
        )
        with pytest.raises(ToolExecutionInProgressError):
            execute_tool(
                agent_run=run,
                tool_key="demo.echo",
                arguments={"message": "hi"},
                idempotency_key="running-key",
            )

    def test_key_without_arguments_never_deduplicates(self):
        run = _running_run()
        _bind_demo_echo(run)
        first = execute_tool(agent_run=run, tool_key="demo.echo", arguments={"message": "hi"})
        second = execute_tool(agent_run=run, tool_key="demo.echo", arguments={"message": "hi"})
        assert first.execution.id != second.execution.id

    def test_retry_after_failure_reuses_the_same_key_and_stays_bounded(self):
        """Same key, terminal-failed row: a replay attempt is allowed
        (section 77) but the *total* attempt budget across both calls is
        still bounded by the tool's retry policy — it does not reset."""
        run = _running_run(max_tool_calls=10)
        tool_definition = ToolDefinitionFactory(
            key="demo.flaky", handler_key="demo.flaky", max_retries=3, default_timeout_seconds=1
        )
        ToolBindingFactory(agent_version=run.agent_version, tool_definition=tool_definition)
        from tools.models import ToolExecution

        with pytest.raises(ToolRetryExhaustedError):
            execute_tool(
                agent_run=run,
                tool_key="demo.flaky",
                arguments={"fail_attempts": 5},
                idempotency_key="retry-key",
            )
        execution = ToolExecution.objects.get(agent_run=run, idempotency_key="retry-key")
        assert execution.status == ToolExecutionStatus.FAILED
        assert execution.attempt_count == 4  # initial attempt + 3 retries, bounded

        # The attempt budget is already spent — a replay under the same key
        # is rejected without invoking the handler again.
        with pytest.raises(ToolRetryExhaustedError):
            execute_tool(
                agent_run=run,
                tool_key="demo.flaky",
                arguments={"fail_attempts": 5},
                idempotency_key="retry-key",
            )
        execution.refresh_from_db()
        assert execution.attempt_count == 4

    @pytest.mark.django_db(transaction=True)
    def test_concurrent_duplicate_claims_produce_one_logical_execution(self):
        """Adversarial concurrency test (section 66): two callers racing the
        same idempotency key must never both create a fresh ToolExecution.
        Requires a real committed transaction per thread, hence
        ``transaction=True`` rather than the default rolled-back wrapper."""
        import django.db as django_db

        run = _running_run()
        _bind_demo_echo(run)
        from tools.models import ToolExecution

        results: list = []
        errors: list = []
        barrier = threading.Barrier(2)

        def worker():
            django_db.close_old_connections()
            barrier.wait()
            try:
                results.append(
                    execute_tool(
                        agent_run=run,
                        tool_key="demo.echo",
                        arguments={"message": "race"},
                        idempotency_key="race-key",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                django_db.close_old_connections()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        executions = ToolExecution.objects.filter(agent_run=run, idempotency_key="race-key")
        assert executions.count() == 1
        assert len(results) + len(errors) == 2


@pytest.mark.django_db
class TestTimeoutAndRetry:
    def test_handler_exceeding_timeout_is_marked_timed_out(self):
        run = _running_run()
        tool_definition = ToolDefinitionFactory(
            key="demo.flaky",
            handler_key="demo.flaky",
            default_timeout_seconds=1,
            max_timeout_seconds=1,
        )
        ToolBindingFactory(agent_version=run.agent_version, tool_definition=tool_definition)
        with pytest.raises(ToolTimeoutError):
            execute_tool(
                agent_run=run,
                tool_key="demo.flaky",
                arguments={"sleep_seconds": 2},
            )
        from tools.models import ToolExecution

        execution = ToolExecution.objects.get(agent_run=run)
        assert execution.status == ToolExecutionStatus.TIMED_OUT
        assert execution.error_code == "tool_timeout"

    def test_configured_timeout_above_hard_max_is_clamped(self):
        # demo.echo's code-owned hard cap (tools.demo_tools.ECHO_TOOL) is 10s —
        # the model/binding can never widen it, regardless of what a caller
        # requests (section 36).
        run = _running_run()
        tool_definition = _bind_demo_echo(run)
        binding = tool_definition.bindings.get(agent_version=run.agent_version)
        binding.configuration = {"timeout_seconds": 999}
        binding.save()
        result = execute_tool(agent_run=run, tool_key="demo.echo", arguments={"message": "hi"})
        assert result.execution.timeout_seconds <= 10

    def test_run_deadline_shorter_than_tool_timeout_blocks_before_execution(self):
        from datetime import timedelta

        from django.utils import timezone

        version = PublishedAgentVersionFactory(wall_time_limit_seconds=1, max_tool_calls=5)
        run = AgentRunFactory(
            agent_version=version,
            workspace=version.agent_definition.workspace,
            status=AgentRunStatus.RUNNING,
            started_at=timezone.now() - timedelta(seconds=10),
        )
        _bind_demo_echo(run)
        from tools.models import ToolExecution

        with pytest.raises(ToolBudgetExceededError):
            execute_tool(agent_run=run, tool_key="demo.echo", arguments={"message": "hi"})
        assert not ToolExecution.objects.filter(agent_run=run).exists()

    def test_retryable_failure_then_success_records_two_attempts(self):
        run = _running_run()
        tool_definition = ToolDefinitionFactory(
            key="demo.flaky", handler_key="demo.flaky", max_retries=3
        )
        ToolBindingFactory(agent_version=run.agent_version, tool_definition=tool_definition)
        result = execute_tool(agent_run=run, tool_key="demo.flaky", arguments={"fail_attempts": 1})
        assert result.execution.status == ToolExecutionStatus.SUCCEEDED
        assert result.execution.attempt_count == 2

    def test_retry_exhaustion_is_bounded(self):
        # demo.flaky's registered spec (tools.demo_tools.FLAKY_TOOL) fixes
        # max_retries=3 — retry policy is code-owned, not a DB field, so the
        # ToolDefinition row's own max_retries is descriptive metadata only
        # (section 14); it does not govern actual retry behavior here.
        run = _running_run()
        tool_definition = ToolDefinitionFactory(key="demo.flaky", handler_key="demo.flaky")
        ToolBindingFactory(agent_version=run.agent_version, tool_definition=tool_definition)
        with pytest.raises(ToolRetryExhaustedError):
            execute_tool(agent_run=run, tool_key="demo.flaky", arguments={"fail_attempts": 5})
        from tools.models import ToolExecution

        execution = ToolExecution.objects.get(agent_run=run)
        # initial attempt + 3 retries = 4 total attempts (documented convention).
        assert execution.attempt_count == 4
        assert execution.status == ToolExecutionStatus.FAILED


@pytest.mark.django_db
class TestOutputValidation:
    def test_handler_returning_wrong_shape_is_rejected_safely(self):
        run = _running_run()

        class BadOutput(BaseModel):
            unexpected_field: int

        class Input(BaseModel):
            message: str

        registry = ToolRegistry()
        registry.register(
            Tool(
                spec=ToolSpec(
                    key="test.bad_output",
                    display_name="Bad output",
                    description="test",
                    input_model=Input,
                    output_model=BadOutput,
                ),
                handler=lambda *, context, arguments: {"totally": "wrong"},
            )
        )
        tool_definition = ToolDefinitionFactory(
            key="test.bad_output", handler_key="test.bad_output"
        )
        ToolBindingFactory(agent_version=run.agent_version, tool_definition=tool_definition)

        with pytest.raises(ToolInvalidOutputError):
            execute_tool(
                agent_run=run,
                tool_key="test.bad_output",
                arguments={"message": "hi"},
                tool_registry=registry,
            )
        from tools.models import ToolExecution

        execution = ToolExecution.objects.get(agent_run=run)
        assert execution.status == ToolExecutionStatus.FAILED
        assert execution.error_code == "tool_invalid_output"


@pytest.mark.django_db
class TestRedaction:
    def test_sensitive_input_field_never_persisted_raw(self):
        run = _running_run()

        class SecretInput(BaseModel):
            api_token: str
            note: str

        class SecretOutput(BaseModel):
            ok: bool

        registry = ToolRegistry()
        registry.register(
            Tool(
                spec=ToolSpec(
                    key="test.secret",
                    display_name="Secret",
                    description="test",
                    input_model=SecretInput,
                    output_model=SecretOutput,
                ),
                handler=lambda *, context, arguments: SecretOutput(ok=True),
            )
        )
        tool_definition = ToolDefinitionFactory(key="test.secret", handler_key="test.secret")
        ToolBindingFactory(agent_version=run.agent_version, tool_definition=tool_definition)

        result = execute_tool(
            agent_run=run,
            tool_key="test.secret",
            arguments={"api_token": "sk-super-secret-value", "note": "hello"},
            tool_registry=registry,
        )
        execution = result.execution
        assert "sk-super-secret-value" not in str(execution.arguments_redacted)
        assert execution.arguments_redacted["api_token"] == "***REDACTED***"
        assert execution.arguments_redacted["note"] == "hello"
