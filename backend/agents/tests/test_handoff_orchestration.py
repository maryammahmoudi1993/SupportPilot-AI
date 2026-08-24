"""Phase 9 Block 5: human handoff as an orchestration outcome, and
deterministic failure/recovery classification (section 41-88, 109)."""

from __future__ import annotations

import pytest

from agents import orchestration, services
from agents.failure_classification import RecoveryAction, classify_terminal_failure
from agents.models import AgentRunStatus, AgentStepType
from agents.providers.errors import (
    ProviderAuthenticationError,
    ProviderRateLimitedError,
)
from agents.providers.fake import DeterministicFakeLLMProvider, FakeLLMScenario
from agents.providers.schemas import NormalizedHandoffRequest, NormalizedToolCall
from conversations.models import Message, MessageSenderType
from conversations.tests.factories import ConversationFactory, MessageFactory
from tickets.models import HumanHandoff, HumanHandoffReason, HumanHandoffStatus
from tickets.tests.factories import HumanHandoffFactory, TicketFactory
from tools.models import ToolExecution
from tools.tests.factories import ToolBindingFactory, ToolDefinitionFactory

from .factories import AgentRunFactory, PublishedAgentVersionFactory


def _provider(monkeypatch, scenarios):
    provider = DeterministicFakeLLMProvider(scenarios)
    monkeypatch.setattr(services, "get_llm_provider", lambda: provider)
    return provider


def _bind(version, key):
    definition = ToolDefinitionFactory(key=key, handler_key=key)
    ToolBindingFactory(agent_version=version, tool_definition=definition)


def _handoff_scenario(reason_code=HumanHandoffReason.CUSTOMER_REQUESTED, summary="Wants a human."):
    return FakeLLMScenario(
        response="",
        handoff_request=NormalizedHandoffRequest(reason_code=reason_code, summary=summary),
    )


def _run_with_conversation(**overrides):
    version = overrides.pop("agent_version", None) or PublishedAgentVersionFactory(
        max_model_calls=3, max_tool_calls=3
    )
    conversation = overrides.pop("conversation", None) or ConversationFactory(
        workspace=version.agent_definition.workspace
    )
    return AgentRunFactory(
        agent_version=version,
        workspace=version.agent_definition.workspace,
        conversation=conversation,
        **overrides,
    )


@pytest.mark.django_db(transaction=True)
class TestExplicitHandoffRequest:
    def test_customer_requested_handoff_creates_one_handoff_and_acknowledgement(self, monkeypatch):
        run = _run_with_conversation()
        _provider(monkeypatch, [_handoff_scenario(summary="Customer wants a human.")])

        result = services.execute_agent_run(run.id)

        assert result.status == AgentRunStatus.HANDED_OFF
        assert HumanHandoff.objects.filter(agent_run=run).count() == 1
        handoff = HumanHandoff.objects.get(agent_run=run)
        assert handoff.reason_code == HumanHandoffReason.CUSTOMER_REQUESTED
        assert handoff.status == HumanHandoffStatus.PENDING
        assert ToolExecution.objects.filter(agent_run=run).count() == 0
        assert result.output_message_id is not None
        message = Message.objects.get(pk=result.output_message_id)
        assert message.sender_type == MessageSenderType.AI_AGENT
        assert (
            Message.objects.filter(
                conversation=run.conversation, sender_type=MessageSenderType.AI_AGENT
            ).count()
            == 1
        )

    def test_no_extra_model_call_is_spent_formulating_the_acknowledgement(self, monkeypatch):
        run = _run_with_conversation()
        provider = _provider(monkeypatch, [_handoff_scenario()])

        result = services.execute_agent_run(run.id)

        assert provider.call_count == 1
        assert result.model_call_count == 1

    def test_handoff_step_events_are_recorded_without_chain_of_thought(self, monkeypatch):
        run = _run_with_conversation()
        _provider(monkeypatch, [_handoff_scenario()])

        result = services.execute_agent_run(run.id)

        step_types = list(result.steps.values_list("step_type", flat=True))
        assert AgentStepType.HANDOFF_REQUESTED in step_types
        assert AgentStepType.RUN_HANDED_OFF in step_types
        for step in result.steps.all():
            assert "reasoning" not in step.safe_metadata
            assert "chain_of_thought" not in step.safe_metadata


@pytest.mark.django_db(transaction=True)
class TestHandoffIdempotency:
    def test_redelivered_execution_does_not_duplicate_the_handoff_or_message(self, monkeypatch):
        run = _run_with_conversation()
        _provider(monkeypatch, [_handoff_scenario()])

        first = services.execute_agent_run(run.id)
        second = services.execute_agent_run(run.id)

        assert first.id == second.id
        assert first.output_message_id == second.output_message_id
        assert HumanHandoff.objects.filter(agent_run=run).count() == 1
        assert (
            Message.objects.filter(
                conversation=run.conversation, sender_type=MessageSenderType.AI_AGENT
            ).count()
            == 1
        )


@pytest.mark.django_db(transaction=True)
class TestHandoffTerminalProtection:
    def test_a_handed_off_run_cannot_be_cancelled(self, monkeypatch):
        from accounts.tests.factories import UserFactory
        from agents.errors import AgentRunNotCancellableError

        run = _run_with_conversation()
        _provider(monkeypatch, [_handoff_scenario()])
        result = services.execute_agent_run(run.id)
        assert result.status == AgentRunStatus.HANDED_OFF

        with pytest.raises(AgentRunNotCancellableError):
            services.cancel_agent_run(workspace=result.workspace, run=result, actor=UserFactory())


@pytest.mark.django_db(transaction=True)
class TestHandoffPrecedenceOverTool:
    def test_a_handoff_request_wins_over_a_tool_call_in_the_same_turn(self, monkeypatch):
        version = PublishedAgentVersionFactory(max_model_calls=3, max_tool_calls=3)
        _bind(version, "demo.echo")
        run = _run_with_conversation(agent_version=version)
        _provider(
            monkeypatch,
            [
                FakeLLMScenario(
                    response="",
                    tool_calls=(
                        NormalizedToolCall(
                            call_id="1", tool_name="demo.echo", arguments={"message": "hi"}
                        ),
                    ),
                    handoff_request=NormalizedHandoffRequest(
                        reason_code=HumanHandoffReason.UNSUPPORTED_ACTION,
                        summary="Cannot safely proceed.",
                    ),
                )
            ],
        )

        result = services.execute_agent_run(run.id)

        assert result.status == AgentRunStatus.HANDED_OFF
        assert ToolExecution.objects.filter(agent_run=run).count() == 0


@pytest.mark.django_db(transaction=True)
class TestMultiTurnThenHandoff:
    def test_prior_tool_history_is_preserved_when_a_later_turn_hands_off(self, monkeypatch):
        version = PublishedAgentVersionFactory(max_model_calls=3, max_tool_calls=3)
        _bind(version, "demo.echo")
        run = _run_with_conversation(agent_version=version)
        _provider(
            monkeypatch,
            [
                FakeLLMScenario(
                    response="",
                    tool_calls=(
                        NormalizedToolCall(
                            call_id="1", tool_name="demo.echo", arguments={"message": "hi"}
                        ),
                    ),
                ),
                _handoff_scenario(
                    reason_code=HumanHandoffReason.UNSUPPORTED_ACTION,
                    summary="Needs an operator after lookup.",
                ),
            ],
        )

        result = services.execute_agent_run(run.id)

        assert result.status == AgentRunStatus.HANDED_OFF
        executions = list(ToolExecution.objects.filter(agent_run=run))
        assert len(executions) == 1
        assert executions[0].status == "succeeded"
        assert HumanHandoff.objects.filter(agent_run=run).count() == 1
        assert result.tool_call_count == 1
        assert result.model_call_count == 2


@pytest.mark.django_db(transaction=True)
class TestFailureClassification:
    def test_classify_retryable_provider_failure_with_conversation_is_handoff(self):
        assert (
            classify_terminal_failure(error_code="provider_rate_limited", has_conversation=True)
            is RecoveryAction.HANDOFF
        )

    def test_classify_retryable_provider_failure_without_conversation_is_fail(self):
        assert (
            classify_terminal_failure(error_code="provider_rate_limited", has_conversation=False)
            is RecoveryAction.FAIL
        )

    def test_classify_configuration_failure_is_always_fail(self):
        assert (
            classify_terminal_failure(
                error_code="provider_authentication_failed", has_conversation=True
            )
            is RecoveryAction.FAIL
        )

    def test_classify_terminal_tool_failure_is_always_fail(self):
        assert (
            classify_terminal_failure(error_code="policy_evaluation_failed", has_conversation=True)
            is RecoveryAction.FAIL
        )

    def test_provider_retry_exhaustion_becomes_a_handoff_end_to_end(self, monkeypatch):
        version = PublishedAgentVersionFactory(max_model_calls=2, max_retry_attempts=2)
        run = _run_with_conversation(agent_version=version)
        provider = _provider(monkeypatch, [FakeLLMScenario(error=ProviderRateLimitedError)])

        result = services.execute_agent_run(run.id)

        assert provider.call_count == 2  # bounded retry, never unbounded
        assert result.status == AgentRunStatus.HANDED_OFF
        handoff = HumanHandoff.objects.get(agent_run=run)
        assert handoff.reason_code == HumanHandoffReason.RUNTIME_FAILURE
        assert "provider_rate_limited" in handoff.safe_summary

    def test_provider_retry_exhaustion_without_a_conversation_fails_the_run(self, monkeypatch):
        version = PublishedAgentVersionFactory(max_model_calls=2, max_retry_attempts=2)
        run = AgentRunFactory(agent_version=version, workspace=version.agent_definition.workspace)
        _provider(monkeypatch, [FakeLLMScenario(error=ProviderRateLimitedError)])

        result = services.execute_agent_run(run.id)

        assert result.status == AgentRunStatus.FAILED
        assert HumanHandoff.objects.filter(agent_run=run).count() == 0

    def test_provider_authentication_failure_fails_the_run_never_a_handoff(self, monkeypatch):
        run = _run_with_conversation()
        _provider(monkeypatch, [FakeLLMScenario(error=ProviderAuthenticationError)])

        result = services.execute_agent_run(run.id)

        assert result.status == AgentRunStatus.FAILED
        assert HumanHandoff.objects.filter(agent_run=run).count() == 0

    def test_safe_business_tool_failure_does_not_escalate_by_default(self, monkeypatch):
        """Section 34, 75: an ordinary safe business failure (unsupported/
        unbound tool) still resolves to a normal final response — the model
        was never forced into a handoff just because one lookup failed."""
        version = PublishedAgentVersionFactory(max_model_calls=3, max_tool_calls=3)
        run = _run_with_conversation(agent_version=version)
        _provider(
            monkeypatch,
            [
                FakeLLMScenario(
                    response="",
                    tool_calls=(
                        NormalizedToolCall(call_id="1", tool_name="nonexistent.tool", arguments={}),
                    ),
                ),
                FakeLLMScenario(response="I can't do that automatically, but here's what I found."),
            ],
        )

        result = services.execute_agent_run(run.id)

        assert result.status == AgentRunStatus.SUCCEEDED
        assert HumanHandoff.objects.filter(agent_run=run).count() == 0


@pytest.mark.django_db(transaction=True)
class TestHandoffReasonSpoof:
    def test_an_unrecognized_reason_code_fails_closed_not_a_fabricated_handoff(self, monkeypatch):
        run = _run_with_conversation()
        _provider(monkeypatch, [_handoff_scenario(reason_code="owner_override")])

        result = services.execute_agent_run(run.id)

        assert result.status == AgentRunStatus.FAILED
        assert result.failure_code == "invalid_handoff_reason"
        assert HumanHandoff.objects.filter(agent_run=run).count() == 0


@pytest.mark.django_db(transaction=True)
class TestHandoffTicketLinkage:
    def test_handoff_links_the_runs_existing_ticket_never_a_foreign_one(self, monkeypatch):
        version = PublishedAgentVersionFactory(max_model_calls=3, max_tool_calls=3)
        conversation = ConversationFactory(workspace=version.agent_definition.workspace)
        ticket = TicketFactory(
            workspace=version.agent_definition.workspace, customer=conversation.customer
        )
        run = AgentRunFactory(
            agent_version=version,
            workspace=version.agent_definition.workspace,
            conversation=conversation,
            ticket=ticket,
        )
        _provider(monkeypatch, [_handoff_scenario()])

        services.execute_agent_run(run.id)

        handoff = HumanHandoff.objects.get(agent_run=run)
        assert handoff.ticket_id == ticket.id


@pytest.mark.django_db(transaction=True)
class TestActiveHandoffGuard:
    def test_a_new_message_on_an_actively_escalated_conversation_never_calls_the_llm(
        self, monkeypatch
    ):
        version = PublishedAgentVersionFactory()
        conversation = ConversationFactory(workspace=version.agent_definition.workspace)
        HumanHandoffFactory(workspace=conversation.workspace, conversation=conversation)
        message = MessageFactory(conversation=conversation, body="Any update?")
        run = AgentRunFactory(
            agent_version=version,
            workspace=conversation.workspace,
            conversation=conversation,
            trigger_message=message,
        )
        provider = _provider(monkeypatch, [FakeLLMScenario(response="should never be used")])

        result = orchestration.execute_support_agent_run(run.id)

        assert provider.call_count == 0
        assert result.status == AgentRunStatus.HANDED_OFF
        assert HumanHandoff.objects.filter(conversation=conversation).count() == 1
        assert result.output_message_id is not None

    def test_a_resolved_handoff_does_not_block_a_new_autonomous_run(self, monkeypatch):
        version = PublishedAgentVersionFactory()
        conversation = ConversationFactory(workspace=version.agent_definition.workspace)
        HumanHandoffFactory(
            workspace=conversation.workspace,
            conversation=conversation,
            status=HumanHandoffStatus.RESOLVED,
        )
        message = MessageFactory(conversation=conversation, body="Any update?")
        run = AgentRunFactory(
            agent_version=version,
            workspace=conversation.workspace,
            conversation=conversation,
            trigger_message=message,
        )
        provider = _provider(monkeypatch, [FakeLLMScenario(response="Here is your update.")])

        result = orchestration.execute_support_agent_run(run.id)

        assert provider.call_count == 1
        assert result.status == AgentRunStatus.SUCCEEDED
