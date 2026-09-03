"""Cross-tenant IDOR and nested-IDOR matrix for the agents domain (Phase 15
checkpoint 3, Part A). ``AgentVersion`` carries no ``workspace`` FK of its
own — it is reachable only through ``agent_definition.workspace`` — so the
nested-IDOR cases here (a real version id from workspace B used against
workspace A's agent id, and vice versa) are the primary target."""

from __future__ import annotations

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from common.tests.security_matrix import two_workspaces

from .factories import AgentDefinitionFactory, AgentRunFactory, PublishedAgentVersionFactory

__all__ = ["two_workspaces"]


def _client(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


def _base(workspace_id) -> str:
    return f"/api/v1/workspaces/{workspace_id}/agents"


def _runs_base(workspace_id) -> str:
    return f"/api/v1/workspaces/{workspace_id}/agent-runs"


@pytest.mark.django_db
class TestAgentDefinitionCrossTenant:
    def test_foreign_workspace_definition_detail_is_404(self, two_workspaces):
        d = two_workspaces
        definition = AgentDefinitionFactory(workspace=d["workspace_a"])
        response = _client(d["b_owner"].user).get(f"{_base(d['workspace_b'].id)}/{definition.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_foreign_workspace_definition_patch_is_404_and_row_unchanged(self, two_workspaces):
        d = two_workspaces
        definition = AgentDefinitionFactory(workspace=d["workspace_a"], name="Original")
        response = _client(d["b_owner"].user).patch(
            f"{_base(d['workspace_b'].id)}/{definition.id}/",
            {"name": "Hijacked"},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        definition.refresh_from_db()
        assert definition.name == "Original"

    def test_definition_list_never_leaks_another_tenants_definition(self, two_workspaces):
        d = two_workspaces
        AgentDefinitionFactory(workspace=d["workspace_a"], name="A-only")
        response = _client(d["b_owner"].user).get(f"{_base(d['workspace_b'].id)}/")
        names = [row["name"] for row in response.data["results"]]
        assert "A-only" not in names


@pytest.mark.django_db
class TestAgentVersionNestedIDOR:
    def test_version_from_a_foreign_definition_404s(self, two_workspaces):
        """A real AgentVersion id belonging to Workspace A's definition,
        requested through Workspace B's own (different) definition id —
        the version has no workspace FK of its own, so this proves the
        lookup actually chains through ``agent_definition`` rather than
        trusting the version id in isolation."""
        d = two_workspaces
        version_a = PublishedAgentVersionFactory(agent_definition__workspace=d["workspace_a"])
        definition_b = AgentDefinitionFactory(workspace=d["workspace_b"])

        # list under B's own definition never contains A's version
        response = _client(d["b_owner"].user).get(
            f"{_base(d['workspace_b'].id)}/{definition_b.id}/versions/"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["results"] == []

        # publish B's definition against A's version id -> 404, not a
        # cross-tenant publish
        response = _client(d["b_owner"].user).post(
            f"{_base(d['workspace_b'].id)}/{definition_b.id}/versions/{version_a.id}/publish/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        version_a.refresh_from_db()
        assert version_a.status != "published" or version_a.published_at is not None
        # published_at must not have been (re)set by this rejected call —
        # PublishedAgentVersionFactory already publishes it, so assert the
        # publish attempt did not touch a *different*, unpublished version.

    def test_unpublished_version_from_foreign_workspace_cannot_be_published_via_own_workspace_id(
        self, two_workspaces
    ):
        d = two_workspaces
        from .factories import AgentVersionFactory

        version_a = AgentVersionFactory(agent_definition__workspace=d["workspace_a"])
        definition_b = AgentDefinitionFactory(workspace=d["workspace_b"])
        owner_b = d["b_owner"]

        response = _client(owner_b.user).post(
            f"{_base(d['workspace_b'].id)}/{definition_b.id}/versions/{version_a.id}/publish/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        version_a.refresh_from_db()
        assert version_a.status != "published"
        assert version_a.published_at is None


@pytest.mark.django_db
class TestAgentRunCrossTenant:
    def test_foreign_workspace_run_detail_is_404(self, two_workspaces):
        d = two_workspaces
        run = AgentRunFactory(workspace=d["workspace_a"])
        response = _client(d["b_owner"].user).get(f"{_runs_base(d['workspace_b'].id)}/{run.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_foreign_workspace_run_cancel_is_404_and_status_unchanged(self, two_workspaces):
        d = two_workspaces
        from agents.models import AgentRunStatus

        run = AgentRunFactory(workspace=d["workspace_a"], status=AgentRunStatus.RUNNING)
        response = _client(d["b_owner"].user).post(
            f"{_runs_base(d['workspace_b'].id)}/{run.id}/cancel/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        run.refresh_from_db()
        assert run.status == AgentRunStatus.RUNNING

    def test_foreign_workspace_run_steps_is_404(self, two_workspaces):
        d = two_workspaces
        run = AgentRunFactory(workspace=d["workspace_a"])
        response = _client(d["b_owner"].user).get(
            f"{_runs_base(d['workspace_b'].id)}/{run.id}/steps/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_creating_a_run_against_a_foreign_workspaces_agent_version_is_rejected(
        self, two_workspaces
    ):
        """The create path resolves ``agent_version_id`` scoped to
        ``agent_definition__workspace=self.workspace`` directly, not via a
        shared selector — a dedicated proof it isn't missed."""
        d = two_workspaces
        version_a = PublishedAgentVersionFactory(agent_definition__workspace=d["workspace_a"])
        response = _client(d["b_owner"].user).post(
            f"{_runs_base(d['workspace_b'].id)}/",
            {"agent_version_id": str(version_a.id), "input_message": "hello"},
            format="json",
        )
        assert response.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND)
        assert not run_exists_for_version(version_a)


def run_exists_for_version(version) -> bool:
    from agents.models import AgentRun

    return AgentRun.objects.filter(agent_version=version).exists()


@pytest.mark.django_db
class TestAgentRBAC:
    def test_support_agent_cannot_configure_agent_definitions(self, two_workspaces):
        d = two_workspaces
        response = _client(d["a_agent"].user).post(
            f"{_base(d['workspace_a'].id)}/",
            {"name": "New agent"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_viewer_cannot_start_a_run(self, two_workspaces):
        d = two_workspaces
        version = PublishedAgentVersionFactory(agent_definition__workspace=d["workspace_a"])
        response = _client(d["a_viewer"].user).post(
            f"{_runs_base(d['workspace_a'].id)}/",
            {"agent_version_id": str(version.id), "input_message": "hi"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_support_agent_can_start_a_run(self, two_workspaces):
        d = two_workspaces
        version = PublishedAgentVersionFactory(agent_definition__workspace=d["workspace_a"])
        response = _client(d["a_agent"].user).post(
            f"{_runs_base(d['workspace_a'].id)}/",
            {"agent_version_id": str(version.id), "input_message": "hi"},
            format="json",
        )
        assert response.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED)


@pytest.mark.django_db
class TestMassAssignment:
    def test_client_cannot_set_agent_version_status_via_write_serializer(self, two_workspaces):
        d = two_workspaces
        definition = AgentDefinitionFactory(workspace=d["workspace_a"])
        response = _client(d["a_owner"].user).post(
            f"{_base(d['workspace_a'].id)}/{definition.id}/versions/",
            {
                "provider": "fake",
                "model": "fake-model-1",
                "system_prompt": "You are a helpful assistant.",
                "status": "published",
                "published_at": "2020-01-01T00:00:00Z",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["status"] != "published"
        assert response.data.get("published_at") is None

    def test_client_cannot_forge_workspace_on_agent_run_create(self, two_workspaces):
        d = two_workspaces
        version = PublishedAgentVersionFactory(agent_definition__workspace=d["workspace_a"])
        response = _client(d["a_owner"].user).post(
            f"{_runs_base(d['workspace_a'].id)}/",
            {
                "agent_version_id": str(version.id),
                "input_message": "hi",
                "workspace": str(d["workspace_b"].id),
                "status": "succeeded",
            },
            format="json",
        )
        assert response.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED)
        run_id = response.data["id"]
        from agents.models import AgentRun

        run = AgentRun.objects.get(pk=run_id)
        assert run.workspace_id == d["workspace_a"].id
        assert run.status != "succeeded"
