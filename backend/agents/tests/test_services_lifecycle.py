import pytest

from accounts.tests.factories import UserFactory
from agents import services
from agents.errors import (
    AgentRunNotCancellableError,
    AgentVersionNotPublishableError,
    AgentVersionNotPublishedError,
)
from agents.models import AgentRunStatus, AgentVersionStatus
from workspaces.tests.factories import WorkspaceFactory

from .factories import (
    AgentDefinitionFactory,
    AgentRunFactory,
    AgentVersionFactory,
    PublishedAgentVersionFactory,
)


@pytest.mark.django_db
class TestAgentDefinitionAndVersionServices:
    def test_create_agent_definition_records_audit_event(self):
        from audit.models import AuditAction, AuditEvent

        workspace = WorkspaceFactory()
        user = UserFactory()
        definition = services.create_agent_definition(
            workspace=workspace, actor=user, data={"name": "Support Bot"}
        )
        assert definition.workspace_id == workspace.id
        assert AuditEvent.objects.filter(
            action=AuditAction.AGENT_DEFINITION_CREATED, target_id=str(definition.id)
        ).exists()

    def test_update_agent_definition_records_audit_event(self):
        from audit.models import AuditAction, AuditEvent

        definition = AgentDefinitionFactory(name="Old Name")
        updated = services.update_agent_definition(
            workspace=definition.workspace,
            definition=definition,
            actor=UserFactory(),
            data={"name": "New Name", "status": "inactive"},
        )
        assert updated.name == "New Name"
        assert updated.status == "inactive"
        assert AuditEvent.objects.filter(
            action=AuditAction.AGENT_DEFINITION_UPDATED, target_id=str(definition.id)
        ).exists()

    def test_create_agent_version_auto_increments(self):
        definition = AgentDefinitionFactory()
        user = UserFactory()
        first = services.create_agent_version(
            workspace=definition.workspace,
            agent_definition=definition,
            actor=user,
            data={"provider": "fake", "model": "fake-model-1"},
        )
        second = services.create_agent_version(
            workspace=definition.workspace,
            agent_definition=definition,
            actor=user,
            data={"provider": "fake", "model": "fake-model-1"},
        )
        assert first.version == 1
        assert second.version == 2

    def test_publish_agent_version_transitions_draft_to_published(self):
        version = AgentVersionFactory()
        published = services.publish_agent_version(
            workspace=version.agent_definition.workspace, version=version, actor=UserFactory()
        )
        assert published.status == AgentVersionStatus.PUBLISHED
        assert published.published_at is not None

    def test_publish_already_published_version_is_rejected(self):
        version = PublishedAgentVersionFactory()
        with pytest.raises(AgentVersionNotPublishableError):
            services.publish_agent_version(
                workspace=version.agent_definition.workspace, version=version, actor=UserFactory()
            )


@pytest.mark.django_db
class TestCreateAgentRun:
    def test_run_requires_a_published_version(self):
        version = AgentVersionFactory()  # draft
        with pytest.raises(AgentVersionNotPublishedError):
            services.create_agent_run(
                workspace=version.agent_definition.workspace,
                agent_version=version,
                actor=UserFactory(),
                input_message="hello",
                trigger="manual",
            )

    def test_run_input_message_is_truncated_to_the_configured_bound(self):
        version = PublishedAgentVersionFactory()
        oversized = "x" * (services.MAX_INPUT_MESSAGE_CHARS + 500)
        run = services.create_agent_run(
            workspace=version.agent_definition.workspace,
            agent_version=version,
            actor=UserFactory(),
            input_message=oversized,
            trigger="manual",
        )
        assert len(run.input_message) == services.MAX_INPUT_MESSAGE_CHARS

    def test_run_starts_pending(self):
        version = PublishedAgentVersionFactory()
        run = services.create_agent_run(
            workspace=version.agent_definition.workspace,
            agent_version=version,
            actor=UserFactory(),
            input_message="hello",
            trigger="manual",
        )
        assert run.status == AgentRunStatus.PENDING


@pytest.mark.django_db
class TestClaimAgentRun:
    def test_claim_transitions_pending_to_running(self):
        run = AgentRunFactory()
        claimed = services.claim_agent_run(run.id)
        assert claimed is not None
        assert claimed.status == AgentRunStatus.RUNNING
        assert claimed.started_at is not None

    def test_second_claim_of_the_same_run_is_a_safe_no_op(self):
        run = AgentRunFactory()
        first = services.claim_agent_run(run.id)
        second = services.claim_agent_run(run.id)
        assert first is not None
        assert second is None  # already running: no duplicate execution claim

    def test_claim_records_audit_event_once(self):
        from audit.models import AuditAction, AuditEvent

        run = AgentRunFactory()
        services.claim_agent_run(run.id)
        services.claim_agent_run(run.id)
        assert (
            AuditEvent.objects.filter(
                action=AuditAction.AGENT_RUN_STARTED, target_id=str(run.id)
            ).count()
            == 1
        )


@pytest.mark.django_db
class TestCancelAgentRun:
    def test_pending_run_can_be_cancelled(self):
        run = AgentRunFactory()
        cancelled = services.cancel_agent_run(workspace=run.workspace, run=run, actor=UserFactory())
        assert cancelled.status == AgentRunStatus.CANCELLED
        assert cancelled.cancelled_at is not None

    def test_running_run_can_be_cancelled(self):
        run = AgentRunFactory()
        services.claim_agent_run(run.id)
        run.refresh_from_db()
        cancelled = services.cancel_agent_run(workspace=run.workspace, run=run, actor=UserFactory())
        assert cancelled.status == AgentRunStatus.CANCELLED

    @pytest.mark.parametrize(
        "status",
        [
            AgentRunStatus.SUCCEEDED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
            AgentRunStatus.BUDGET_EXCEEDED,
            # Phase 9 Block 6 (section 40): HANDED_OFF is a Block 5 terminal
            # status added after this parametrize list was first written —
            # it must be just as unreopenable as any other terminal state.
            AgentRunStatus.HANDED_OFF,
        ],
    )
    def test_terminal_run_cannot_be_cancelled_again(self, status):
        run = AgentRunFactory(status=status)
        with pytest.raises(AgentRunNotCancellableError):
            services.cancel_agent_run(workspace=run.workspace, run=run, actor=UserFactory())

    def test_cancellation_is_idempotent_guard_not_silent_success(self):
        run = AgentRunFactory()
        services.cancel_agent_run(workspace=run.workspace, run=run, actor=UserFactory())
        run.refresh_from_db()
        with pytest.raises(AgentRunNotCancellableError):
            services.cancel_agent_run(workspace=run.workspace, run=run, actor=UserFactory())
