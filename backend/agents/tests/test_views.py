from unittest import mock

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from agents.models import AgentRunStatus
from agents.providers.fake import DeterministicFakeLLMProvider, FakeLLMScenario
from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceFactory, WorkspaceMembershipFactory

from .factories import (
    AgentDefinitionFactory,
    AgentRunFactory,
    AgentStepFactory,
    AgentVersionFactory,
    PublishedAgentVersionFactory,
)


def _client(user=None):
    client = APIClient()
    if user:
        client.force_authenticate(user=user)
    return client


def _base(workspace):
    return f"/api/v1/workspaces/{workspace.id}/agents"


def _runs_base(workspace):
    return f"/api/v1/workspaces/{workspace.id}/agent-runs"


@pytest.mark.django_db
class TestAgentDefinitionApi:
    def test_anonymous_is_401_and_foreign_workspace_is_404(self):
        workspace = WorkspaceFactory()
        assert _client().get(f"{_base(workspace)}/").status_code == 401
        membership = WorkspaceMembershipFactory()
        assert _client(membership.user).get(f"{_base(workspace)}/").status_code == 404

    @pytest.mark.parametrize(
        "role,allowed",
        [
            (WorkspaceRole.OWNER, True),
            (WorkspaceRole.ADMIN, True),
            (WorkspaceRole.SUPPORT_MANAGER, True),
            (WorkspaceRole.SUPPORT_AGENT, False),
            (WorkspaceRole.VIEWER, False),
        ],
    )
    def test_configure_rbac_and_all_roles_can_read(self, role, allowed):
        membership = WorkspaceMembershipFactory(role=role)
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/", {"name": "Support Bot"}, format="json"
        )
        assert response.status_code == (201 if allowed else 403)
        assert _client(membership.user).get(f"{_base(membership.workspace)}/").status_code == 200

    def test_definition_detail_is_tenant_scoped(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.VIEWER)
        foreign = AgentDefinitionFactory()
        response = _client(membership.user).get(f"{_base(membership.workspace)}/{foreign.id}/")
        assert response.status_code == 404

    def test_manager_patches_a_definition(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        definition = AgentDefinitionFactory(workspace=membership.workspace, name="Old Name")
        response = _client(membership.user).patch(
            f"{_base(membership.workspace)}/{definition.id}/",
            {"name": "New Name", "status": "inactive"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["name"] == "New Name"
        assert response.data["status"] == "inactive"

    def test_support_agent_cannot_patch_a_definition(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.SUPPORT_AGENT)
        definition = AgentDefinitionFactory(workspace=membership.workspace)
        response = _client(membership.user).patch(
            f"{_base(membership.workspace)}/{definition.id}/", {"name": "x"}, format="json"
        )
        assert response.status_code == 403

    def test_client_cannot_set_workspace_or_created_by(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        other_user = WorkspaceMembershipFactory().user
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/",
            {
                "name": "Injected Agent",
                "workspace": str(WorkspaceFactory().id),
                "created_by": str(other_user.id),
            },
            format="json",
        )
        assert response.status_code == 201
        # The definition must belong to the caller's own workspace regardless
        # of any client-supplied workspace field.
        listing = _client(membership.user).get(f"{_base(membership.workspace)}/").data
        assert listing["count"] == 1


@pytest.mark.django_db
class TestAgentVersionApi:
    def test_manager_creates_and_publishes_a_version(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.SUPPORT_MANAGER)
        definition = AgentDefinitionFactory(workspace=membership.workspace)
        client = _client(membership.user)

        create = client.post(
            f"{_base(membership.workspace)}/{definition.id}/versions/",
            {"provider": "fake", "model": "fake-model-1", "max_model_calls": 2},
            format="json",
        )
        assert create.status_code == 201
        assert create.data["status"] == "draft"
        version_id = create.data["id"]

        publish = client.post(
            f"{_base(membership.workspace)}/{definition.id}/versions/{version_id}/publish/"
        )
        assert publish.status_code == 200
        assert publish.data["status"] == "published"

        publish_again = client.post(
            f"{_base(membership.workspace)}/{definition.id}/versions/{version_id}/publish/"
        )
        assert publish_again.status_code == 409

    def test_agent_agent_cannot_configure_versions(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.SUPPORT_AGENT)
        definition = AgentDefinitionFactory(workspace=membership.workspace)
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/{definition.id}/versions/",
            {"provider": "fake", "model": "fake-model-1"},
            format="json",
        )
        assert response.status_code == 403

    def test_invalid_budget_values_are_rejected(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        definition = AgentDefinitionFactory(workspace=membership.workspace)
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/{definition.id}/versions/",
            {"provider": "fake", "model": "fake-model-1", "max_model_calls": 0},
            format="json",
        )
        assert response.status_code == 400

    def test_list_versions_for_a_definition(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.VIEWER)
        definition = AgentDefinitionFactory(workspace=membership.workspace)
        AgentVersionFactory(agent_definition=definition, version=1)
        AgentVersionFactory(agent_definition=definition, version=2)
        response = _client(membership.user).get(
            f"{_base(membership.workspace)}/{definition.id}/versions/"
        )
        assert response.status_code == 200
        assert response.data["count"] == 2

    def test_version_from_foreign_definition_404s(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        foreign_version = PublishedAgentVersionFactory()
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/{foreign_version.agent_definition_id}/versions/{foreign_version.id}/publish/"
        )
        assert response.status_code == 404


@pytest.mark.django_db
class TestAgentRunApi:
    @pytest.mark.django_db(transaction=True)
    def test_start_run_dispatches_synchronously_in_eager_mode(self, settings, monkeypatch):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        settings.CELERY_TASK_EAGER_PROPAGATES = True
        provider = DeterministicFakeLLMProvider(FakeLLMScenario(response="Try restarting the app."))
        monkeypatch.setattr("agents.services.get_llm_provider", lambda: provider)

        membership = WorkspaceMembershipFactory(role=WorkspaceRole.SUPPORT_AGENT)
        version = PublishedAgentVersionFactory(agent_definition__workspace=membership.workspace)

        response = _client(membership.user).post(
            f"{_runs_base(membership.workspace)}/",
            {"agent_version_id": str(version.id), "input_message": "It crashed again."},
            format="json",
        )
        assert response.status_code == 201
        run_id = response.data["id"]

        detail = _client(membership.user).get(f"{_runs_base(membership.workspace)}/{run_id}/")
        assert detail.status_code == 200
        assert detail.data["status"] == AgentRunStatus.SUCCEEDED
        assert detail.data["final_response"] == "Try restarting the app."

        steps = _client(membership.user).get(f"{_runs_base(membership.workspace)}/{run_id}/steps/")
        assert steps.status_code == 200
        assert len(steps.data) > 0

    def test_viewer_cannot_start_a_run(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.VIEWER)
        version = PublishedAgentVersionFactory(agent_definition__workspace=membership.workspace)
        response = _client(membership.user).post(
            f"{_runs_base(membership.workspace)}/",
            {"agent_version_id": str(version.id), "input_message": "hi"},
            format="json",
        )
        assert response.status_code == 403

    def test_run_against_unpublished_version_is_rejected(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.SUPPORT_AGENT)
        version = AgentVersionFactory(agent_definition__workspace=membership.workspace)  # draft
        response = _client(membership.user).post(
            f"{_runs_base(membership.workspace)}/",
            {"agent_version_id": str(version.id), "input_message": "hi"},
            format="json",
        )
        assert response.status_code == 400
        assert response.data["error"]["code"] == "agent_version_not_published"

    def test_run_creation_is_rate_limited_but_listing_is_not(self):
        # Regression (Phase 14, Section 19-20/24): AGENT_EXECUTION throttling
        # must apply only to the run-creating POST, never to GET listing.
        cache.clear()
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.SUPPORT_AGENT)
        version = AgentVersionFactory(agent_definition__workspace=membership.workspace)  # draft
        client = _client(membership.user)

        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"agent_execution": "1/min"}):
            first = client.post(
                f"{_runs_base(membership.workspace)}/",
                {"agent_version_id": str(version.id), "input_message": "hi"},
                format="json",
            )
            assert first.status_code == 400  # draft version, rejected before throttle exhausted twice

            second = client.post(
                f"{_runs_base(membership.workspace)}/",
                {"agent_version_id": str(version.id), "input_message": "hi"},
                format="json",
            )
            assert second.status_code == 429
            assert second.data["error"]["code"] == "rate_limited"

            # Listing runs is a separate throttle scope (none) — unaffected.
            listing = client.get(f"{_runs_base(membership.workspace)}/")
            assert listing.status_code == 200
        cache.clear()

    def test_run_can_link_a_conversation_and_ticket_from_the_same_workspace(self):
        from conversations.tests.factories import ConversationFactory
        from tickets.tests.factories import TicketFactory

        membership = WorkspaceMembershipFactory(role=WorkspaceRole.SUPPORT_AGENT)
        version = PublishedAgentVersionFactory(agent_definition__workspace=membership.workspace)
        conversation = ConversationFactory(workspace=membership.workspace)
        ticket = TicketFactory(workspace=membership.workspace)

        response = _client(membership.user).post(
            f"{_runs_base(membership.workspace)}/",
            {
                "agent_version_id": str(version.id),
                "input_message": "hi",
                "conversation_id": str(conversation.id),
                "ticket_id": str(ticket.id),
            },
            format="json",
        )
        assert response.status_code == 201
        assert str(response.data["conversation_id"]) == str(conversation.id)
        assert str(response.data["ticket_id"]) == str(ticket.id)

    @pytest.mark.django_db(transaction=True)
    def test_orchestrated_run_via_trigger_message_persists_the_final_message(
        self, settings, monkeypatch
    ):
        from conversations.models import Message, MessageSenderType
        from conversations.tests.factories import ConversationFactory, MessageFactory

        settings.CELERY_TASK_ALWAYS_EAGER = True
        settings.CELERY_TASK_EAGER_PROPAGATES = True
        provider = DeterministicFakeLLMProvider(FakeLLMScenario(response="It ships tomorrow."))
        monkeypatch.setattr("agents.services.get_llm_provider", lambda: provider)

        membership = WorkspaceMembershipFactory(role=WorkspaceRole.SUPPORT_AGENT)
        version = PublishedAgentVersionFactory(agent_definition__workspace=membership.workspace)
        conversation = ConversationFactory(workspace=membership.workspace)
        message = MessageFactory(conversation=conversation, body="Where is my order?")

        response = _client(membership.user).post(
            f"{_runs_base(membership.workspace)}/",
            {
                "agent_version_id": str(version.id),
                "conversation_id": str(conversation.id),
                "trigger_message_id": str(message.id),
            },
            format="json",
        )
        assert response.status_code == 201
        run_id = response.data["id"]
        detail = _client(membership.user).get(f"{_runs_base(membership.workspace)}/{run_id}/")
        assert detail.data["status"] == AgentRunStatus.SUCCEEDED
        assert (
            Message.objects.filter(
                conversation=conversation, sender_type=MessageSenderType.AI_AGENT
            ).count()
            == 1
        )

        # A client retry of the same trigger message reuses the one logical
        # run rather than starting a second one (section 19, 110-111).
        retry = _client(membership.user).post(
            f"{_runs_base(membership.workspace)}/",
            {
                "agent_version_id": str(version.id),
                "conversation_id": str(conversation.id),
                "trigger_message_id": str(message.id),
            },
            format="json",
        )
        assert retry.status_code == 201
        assert retry.data["id"] == response.data["id"]

    def test_trigger_message_from_another_conversation_404s(self):
        from conversations.tests.factories import ConversationFactory, MessageFactory

        membership = WorkspaceMembershipFactory(role=WorkspaceRole.SUPPORT_AGENT)
        version = PublishedAgentVersionFactory(agent_definition__workspace=membership.workspace)
        conversation = ConversationFactory(workspace=membership.workspace)
        foreign_message = MessageFactory()

        response = _client(membership.user).post(
            f"{_runs_base(membership.workspace)}/",
            {
                "agent_version_id": str(version.id),
                "conversation_id": str(conversation.id),
                "trigger_message_id": str(foreign_message.id),
            },
            format="json",
        )
        assert response.status_code == 404

    def test_run_with_foreign_conversation_404s(self):
        from conversations.tests.factories import ConversationFactory

        membership = WorkspaceMembershipFactory(role=WorkspaceRole.SUPPORT_AGENT)
        version = PublishedAgentVersionFactory(agent_definition__workspace=membership.workspace)
        foreign_conversation = ConversationFactory()
        response = _client(membership.user).post(
            f"{_runs_base(membership.workspace)}/",
            {
                "agent_version_id": str(version.id),
                "input_message": "hi",
                "conversation_id": str(foreign_conversation.id),
            },
            format="json",
        )
        assert response.status_code == 404

    def test_run_against_foreign_workspace_version_404s(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.SUPPORT_AGENT)
        foreign_version = PublishedAgentVersionFactory()
        response = _client(membership.user).post(
            f"{_runs_base(membership.workspace)}/",
            {"agent_version_id": str(foreign_version.id), "input_message": "hi"},
            format="json",
        )
        assert response.status_code == 404

    def test_run_detail_and_steps_are_tenant_scoped(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.VIEWER)
        foreign_run = AgentRunFactory()
        AgentStepFactory(run=foreign_run, workspace=foreign_run.workspace)
        assert (
            _client(membership.user)
            .get(f"{_runs_base(membership.workspace)}/{foreign_run.id}/")
            .status_code
            == 404
        )
        assert (
            _client(membership.user)
            .get(f"{_runs_base(membership.workspace)}/{foreign_run.id}/steps/")
            .status_code
            == 404
        )

    def test_cancel_pending_run(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.SUPPORT_MANAGER)
        run = AgentRunFactory(workspace=membership.workspace)
        response = _client(membership.user).post(
            f"{_runs_base(membership.workspace)}/{run.id}/cancel/"
        )
        assert response.status_code == 200
        assert response.data["status"] == AgentRunStatus.CANCELLED

    def test_cancel_terminal_run_is_conflict(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.SUPPORT_MANAGER)
        run = AgentRunFactory(workspace=membership.workspace, status=AgentRunStatus.SUCCEEDED)
        response = _client(membership.user).post(
            f"{_runs_base(membership.workspace)}/{run.id}/cancel/"
        )
        assert response.status_code == 409

    def test_viewer_cannot_cancel(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.VIEWER)
        run = AgentRunFactory(workspace=membership.workspace)
        response = _client(membership.user).post(
            f"{_runs_base(membership.workspace)}/{run.id}/cancel/"
        )
        assert response.status_code == 403

    def test_client_cannot_set_status_or_usage_counters(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.SUPPORT_AGENT)
        version = PublishedAgentVersionFactory(agent_definition__workspace=membership.workspace)
        response = _client(membership.user).post(
            f"{_runs_base(membership.workspace)}/",
            {
                "agent_version_id": str(version.id),
                "input_message": "hi",
                "status": "succeeded",
                "model_call_count": 999,
                "total_tokens": 999999,
                "estimated_cost_usd": "100.00",
            },
            format="json",
        )
        assert response.status_code == 201
        assert response.data["status"] == AgentRunStatus.PENDING
        assert response.data["model_call_count"] == 0
        assert response.data["total_tokens"] == 0

    def test_input_message_over_the_limit_is_rejected(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.SUPPORT_AGENT)
        version = PublishedAgentVersionFactory(agent_definition__workspace=membership.workspace)
        response = _client(membership.user).post(
            f"{_runs_base(membership.workspace)}/",
            {"agent_version_id": str(version.id), "input_message": "x" * 20000},
            format="json",
        )
        assert response.status_code == 400

    def test_run_listing_never_returns_an_unbounded_step_history(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.VIEWER)
        run = AgentRunFactory(workspace=membership.workspace)
        for i in range(1, 260):
            AgentStepFactory(run=run, workspace=run.workspace, sequence=i)
        response = _client(membership.user).get(
            f"{_runs_base(membership.workspace)}/{run.id}/steps/"
        )
        assert response.status_code == 200
        assert len(response.data) <= 200
