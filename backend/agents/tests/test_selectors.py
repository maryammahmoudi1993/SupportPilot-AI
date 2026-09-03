import pytest
from django.http import Http404
from rest_framework.exceptions import ValidationError

from agents import selectors
from workspaces.tests.factories import WorkspaceFactory

from .factories import (
    AgentDefinitionFactory,
    AgentRunFactory,
    AgentStepFactory,
    PublishedAgentVersionFactory,
)


@pytest.mark.django_db
class TestAgentSelectorTenantIsolation:
    def test_definition_from_another_workspace_404s(self):
        foreign = AgentDefinitionFactory()
        with pytest.raises(Http404):
            selectors.agent_definition_get_for_workspace_or_404(
                workspace=WorkspaceFactory(), agent_id=foreign.id
            )

    def test_version_from_another_workspace_404s(self):
        own_definition = AgentDefinitionFactory()
        foreign_version = PublishedAgentVersionFactory()
        with pytest.raises(Http404):
            selectors.agent_version_get_for_workspace_or_404(
                workspace=own_definition.workspace,
                agent_definition=own_definition,
                version_id=foreign_version.id,
            )

    def test_run_from_another_workspace_404s(self):
        foreign_run = AgentRunFactory()
        with pytest.raises(Http404):
            selectors.agent_run_get_for_workspace_or_404(
                workspace=WorkspaceFactory(), run_id=foreign_run.id
            )

    def test_nonexistent_uuid_also_404s_identically(self):
        import uuid

        with pytest.raises(Http404):
            selectors.agent_run_get_for_workspace_or_404(
                workspace=WorkspaceFactory(), run_id=uuid.uuid4()
            )

    def test_step_listing_is_scoped_to_workspace_and_run(self):
        run = AgentRunFactory()
        AgentStepFactory(run=run, workspace=run.workspace, sequence=1)
        AgentStepFactory(run=run, workspace=run.workspace, sequence=2)
        other_run = AgentRunFactory()
        AgentStepFactory(run=other_run, workspace=other_run.workspace, sequence=1)

        steps = selectors.agent_step_list_for_run(workspace=run.workspace, run=run)
        assert [s.sequence for s in steps] == [1, 2]

    def test_step_listing_is_bounded(self):
        run = AgentRunFactory()
        for i in range(1, 6):
            AgentStepFactory(run=run, workspace=run.workspace, sequence=i)
        steps = selectors.agent_step_list_for_run(workspace=run.workspace, run=run, limit=3)
        assert len(steps) == 3


@pytest.mark.django_db
class TestAgentSelectorListing:
    def test_definition_list_filters_by_status(self):
        workspace = WorkspaceFactory()
        AgentDefinitionFactory(workspace=workspace, status="active")
        AgentDefinitionFactory(workspace=workspace, status="archived")
        active_only = selectors.agent_definition_list_for_workspace(
            workspace=workspace, status="active"
        )
        assert active_only.count() == 1

    def test_version_list_for_definition_is_scoped_and_ordered(self):
        definition = AgentDefinitionFactory()
        from .factories import AgentVersionFactory

        AgentVersionFactory(agent_definition=definition, version=1)
        AgentVersionFactory(agent_definition=definition, version=2)
        versions = selectors.agent_version_list_for_definition(
            workspace=definition.workspace, agent_definition=definition
        )
        assert [v.version for v in versions] == [2, 1]

    def test_run_list_with_malformed_agent_id_fails_predictably(self):
        # Regression (Phase 14, Section 7): a malformed filter must not be
        # silently treated as "no matches" — that would look like an
        # honestly-applied filter that simply found nothing.
        workspace = WorkspaceFactory()
        AgentRunFactory(workspace=workspace)
        with pytest.raises(ValidationError):
            selectors.agent_run_list_for_workspace(
                workspace=workspace, agent_definition_id="not-a-uuid"
            )

    def test_run_list_filters_by_status_and_agent(self):
        version = PublishedAgentVersionFactory()
        run = AgentRunFactory(agent_version=version, workspace=version.agent_definition.workspace)
        run.status = "succeeded"
        run.save()
        AgentRunFactory(agent_version=version, workspace=version.agent_definition.workspace)

        succeeded = selectors.agent_run_list_for_workspace(
            workspace=version.agent_definition.workspace, status="succeeded"
        )
        assert list(succeeded) == [run]

        by_agent = selectors.agent_run_list_for_workspace(
            workspace=version.agent_definition.workspace,
            agent_definition_id=version.agent_definition_id,
        )
        assert by_agent.count() == 2
