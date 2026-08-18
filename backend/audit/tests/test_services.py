"""Audit foundation tests: the write path, safe metadata, and the absence
of any update/delete path."""

import pytest

from audit.models import AuditAction, AuditEvent
from audit.services import record_event
from workspaces.tests.factories import UserFactory, WorkspaceFactory


@pytest.mark.django_db
class TestRecordEvent:
    def test_persists_expected_fields(self):
        actor = UserFactory()
        workspace = WorkspaceFactory()

        event = record_event(
            action=AuditAction.WORKSPACE_CREATED,
            target_type="workspace",
            target_id=str(workspace.id),
            actor=actor,
            workspace=workspace,
            metadata={"name": workspace.name},
            request_id="req-123",
        )

        stored = AuditEvent.objects.get(pk=event.pk)
        assert stored.action == AuditAction.WORKSPACE_CREATED
        assert stored.actor == actor
        assert stored.workspace == workspace
        assert stored.target_type == "workspace"
        assert stored.target_id == str(workspace.id)
        assert stored.metadata == {"name": workspace.name}
        assert stored.request_id == "req-123"

    def test_actor_may_be_null_for_system_events(self):
        event = record_event(
            action=AuditAction.WORKSPACE_UPDATED,
            target_type="workspace",
            target_id="00000000-0000-0000-0000-000000000000",
        )
        assert event.actor is None

    def test_metadata_defaults_to_empty_dict(self):
        event = record_event(
            action=AuditAction.WORKSPACE_UPDATED,
            target_type="workspace",
            target_id="x",
        )
        assert event.metadata == {}

    def test_no_update_or_delete_service_is_exposed(self):
        # The audit app's public API is exactly `record_event` — there is no
        # update/delete function to accidentally call.
        import audit.services as audit_services

        public_names = [name for name in dir(audit_services) if not name.startswith("_")]
        assert "update_event" not in public_names
        assert "delete_event" not in public_names


@pytest.mark.django_db
class TestAuditEventModel:
    def test_string_representation(self):
        event = record_event(
            action=AuditAction.WORKSPACE_CREATED, target_type="workspace", target_id="abc"
        )
        assert str(event) == "workspace.created on workspace:abc"

    def test_ordered_most_recent_first(self):
        first = record_event(
            action=AuditAction.WORKSPACE_CREATED, target_type="workspace", target_id="1"
        )
        second = record_event(
            action=AuditAction.WORKSPACE_CREATED, target_type="workspace", target_id="2"
        )
        ordered = list(AuditEvent.objects.all())
        assert ordered[0] == second
        assert ordered[1] == first
