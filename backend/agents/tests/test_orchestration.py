"""Phase 9 orchestration boundary: idempotent run start, final-message
persistence, and cancellation cascades — the block 1 foundation the fuller
context/RAG/multi-tool orchestration builds on."""

from __future__ import annotations

import pytest

from accounts.tests.factories import UserFactory
from agents import orchestration, services
from agents.models import AgentRunStatus, AgentRunTrigger
from agents.orchestration import TriggerMessageMismatchError
from agents.providers.fake import DeterministicFakeLLMProvider, FakeLLMScenario
from conversations.models import Message, MessageSenderType
from conversations.tests.factories import ConversationFactory, MessageFactory
from tickets.models import HumanHandoffStatus
from tickets.tests.factories import HumanHandoffFactory

from .factories import AgentRunFactory, PublishedAgentVersionFactory


def _use_fake_provider(monkeypatch, scenario):
    provider = DeterministicFakeLLMProvider(scenario)
    monkeypatch.setattr(services, "get_llm_provider", lambda: provider)
    return provider


@pytest.mark.django_db
class TestStartSupportAgentRun:
    def test_creates_a_run_bound_to_the_trigger_message(self):
        conversation = ConversationFactory()
        message = MessageFactory(conversation=conversation, body="Where is my order?")
        version = PublishedAgentVersionFactory(agent_definition__workspace=conversation.workspace)
        run = orchestration.start_support_agent_run(
            workspace=conversation.workspace,
            actor=UserFactory(),
            conversation=conversation,
            trigger_message=message,
            agent_version=version,
        )
        assert run.trigger_message_id == message.id
        assert run.trigger == AgentRunTrigger.CONVERSATION
        assert run.input_message == "Where is my order?"

    def test_a_duplicate_trigger_message_reuses_the_same_run(self):
        conversation = ConversationFactory()
        message = MessageFactory(conversation=conversation)
        version = PublishedAgentVersionFactory(agent_definition__workspace=conversation.workspace)
        actor = UserFactory()
        first = orchestration.start_support_agent_run(
            workspace=conversation.workspace,
            actor=actor,
            conversation=conversation,
            trigger_message=message,
            agent_version=version,
        )
        second = orchestration.start_support_agent_run(
            workspace=conversation.workspace,
            actor=actor,
            conversation=conversation,
            trigger_message=message,
            agent_version=version,
        )
        assert second.id == first.id
        from agents.models import AgentRun

        assert AgentRun.objects.filter(trigger_message=message).count() == 1

    def test_a_message_from_another_conversation_is_rejected(self):
        conversation = ConversationFactory()
        other_conversation = ConversationFactory(workspace=conversation.workspace)
        foreign_message = MessageFactory(conversation=other_conversation)
        version = PublishedAgentVersionFactory(agent_definition__workspace=conversation.workspace)
        with pytest.raises(TriggerMessageMismatchError):
            orchestration.start_support_agent_run(
                workspace=conversation.workspace,
                actor=UserFactory(),
                conversation=conversation,
                trigger_message=foreign_message,
                agent_version=version,
            )

    def test_a_message_from_another_workspace_is_rejected(self):
        conversation = ConversationFactory()
        foreign_message = MessageFactory()
        version = PublishedAgentVersionFactory(agent_definition__workspace=conversation.workspace)
        with pytest.raises(TriggerMessageMismatchError):
            orchestration.start_support_agent_run(
                workspace=conversation.workspace,
                actor=UserFactory(),
                conversation=conversation,
                trigger_message=foreign_message,
                agent_version=version,
            )


@pytest.mark.django_db
class TestFinalResponsePersistence:
    def test_a_successful_run_persists_one_assistant_message(self, monkeypatch):
        _use_fake_provider(monkeypatch, FakeLLMScenario(response="Your order ships tomorrow."))
        conversation = ConversationFactory()
        version = PublishedAgentVersionFactory(agent_definition__workspace=conversation.workspace)
        run = AgentRunFactory(
            workspace=conversation.workspace,
            agent_version=version,
            conversation=conversation,
            input_message="Where is my order?",
        )

        result = orchestration.execute_support_agent_run(run.id)

        assert result.status == AgentRunStatus.SUCCEEDED
        assert result.output_message_id is not None
        message = Message.objects.get(pk=result.output_message_id)
        assert message.body == "Your order ships tomorrow."
        assert message.sender_type == MessageSenderType.AI_AGENT
        assert message.sender_membership_id is None
        assert (
            Message.objects.filter(
                conversation=conversation, sender_type=MessageSenderType.AI_AGENT
            ).count()
            == 1
        )

    def test_redelivered_execution_does_not_duplicate_the_message(self, monkeypatch):
        _use_fake_provider(monkeypatch, FakeLLMScenario(response="answer"))
        conversation = ConversationFactory()
        version = PublishedAgentVersionFactory(agent_definition__workspace=conversation.workspace)
        run = AgentRunFactory(
            workspace=conversation.workspace, agent_version=version, conversation=conversation
        )

        first = orchestration.execute_support_agent_run(run.id)
        # A redelivered Celery task calling execute again for an
        # already-terminal run must not create a second message.
        second = orchestration.execute_support_agent_run(run.id)

        assert first.output_message_id == second.output_message_id
        assert (
            Message.objects.filter(
                conversation=conversation, sender_type=MessageSenderType.AI_AGENT
            ).count()
            == 1
        )

    def test_a_run_without_a_conversation_creates_no_message(self, monkeypatch):
        _use_fake_provider(monkeypatch, FakeLLMScenario(response="answer"))
        run = AgentRunFactory(conversation=None)

        result = orchestration.execute_support_agent_run(run.id)

        assert result.status == AgentRunStatus.SUCCEEDED
        assert result.output_message_id is None


@pytest.mark.django_db
class TestCancelSupportAgentRun:
    def test_cancelling_a_run_cancels_its_active_handoff(self):
        run = AgentRunFactory(status=AgentRunStatus.RUNNING)
        handoff = HumanHandoffFactory(workspace=run.workspace, agent_run=run)

        orchestration.cancel_support_agent_run(
            workspace=run.workspace, run=run, actor=UserFactory()
        )

        handoff.refresh_from_db()
        run.refresh_from_db()
        assert run.status == AgentRunStatus.CANCELLED
        assert handoff.status == HumanHandoffStatus.CANCELLED
