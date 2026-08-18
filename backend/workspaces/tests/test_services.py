"""Service-layer tests: creation, updates, member management, and the
atomic ownership-transfer invariant."""

from unittest import mock

import pytest
from django.db import IntegrityError
from rest_framework.exceptions import PermissionDenied, ValidationError

from audit.models import AuditEvent
from common.exceptions import ConflictError
from workspaces import services
from workspaces.models import WorkspaceMembership, WorkspaceRole

from .factories import UserFactory, WorkspaceFactory, WorkspaceMembershipFactory


@pytest.mark.django_db
class TestCreateWorkspace:
    def test_creates_workspace_with_creator_as_owner(self):
        user = UserFactory()

        workspace = services.create_workspace(actor=user, name="Acme")

        membership = WorkspaceMembership.objects.get(workspace=workspace, user=user)
        assert membership.role == WorkspaceRole.OWNER
        assert WorkspaceMembership.objects.filter(workspace=workspace).count() == 1

    def test_records_audit_event(self):
        user = UserFactory()

        workspace = services.create_workspace(actor=user, name="Acme", request_id="req-1")

        event = AuditEvent.objects.get(target_type="workspace", target_id=str(workspace.id))
        assert event.action == "workspace.created"
        assert event.actor == user
        assert event.workspace == workspace
        assert event.request_id == "req-1"

    def test_blank_name_is_rejected(self):
        user = UserFactory()
        with pytest.raises(ValidationError):
            services.create_workspace(actor=user, name="   ")

    def test_transaction_rolls_back_when_membership_creation_fails(self):
        user = UserFactory()
        from workspaces.models import Workspace as WorkspaceModel

        with mock.patch(
            "workspaces.models.WorkspaceMembership.objects.create",
            side_effect=IntegrityError("boom"),
        ):
            with pytest.raises(IntegrityError):
                services.create_workspace(actor=user, name="Acme Rollback")

        assert not WorkspaceModel.objects.filter(name="Acme Rollback").exists()

    def test_transaction_rolls_back_when_audit_persistence_fails(self):
        user = UserFactory()
        from workspaces.models import Workspace as WorkspaceModel

        with mock.patch("workspaces.services.record_event", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                services.create_workspace(actor=user, name="Acme Audit Rollback")

        assert not WorkspaceModel.objects.filter(name="Acme Audit Rollback").exists()
        assert not WorkspaceMembership.objects.filter(user=user).exists()


@pytest.mark.django_db
class TestUpdateWorkspace:
    def test_updates_name_and_records_audit(self):
        workspace = WorkspaceFactory(name="Old Name")
        actor = UserFactory()

        updated = services.update_workspace(workspace=workspace, actor=actor, name="New Name")

        assert updated.name == "New Name"
        event = AuditEvent.objects.get(target_type="workspace", action="workspace.updated")
        assert event.metadata == {"name": "New Name"}

    def test_blank_name_is_rejected(self):
        workspace = WorkspaceFactory()
        with pytest.raises(ValidationError):
            services.update_workspace(workspace=workspace, actor=UserFactory(), name="   ")

    def test_no_op_when_name_not_supplied(self):
        workspace = WorkspaceFactory(name="Stays")
        services.update_workspace(workspace=workspace, actor=UserFactory(), name=None)
        workspace.refresh_from_db()
        assert workspace.name == "Stays"


@pytest.mark.django_db
class TestAddWorkspaceMember:
    def test_owner_can_add_support_agent(self):
        workspace = WorkspaceFactory()
        owner_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)
        target_user = UserFactory(email="agent@example.com")

        membership = services.add_workspace_member(
            workspace=workspace,
            actor=owner_membership.user,
            actor_membership=owner_membership,
            email="Agent@Example.com",
            role=WorkspaceRole.SUPPORT_AGENT,
        )

        assert membership.user == target_user
        assert membership.role == WorkspaceRole.SUPPORT_AGENT
        assert membership.is_active is True

    def test_owner_can_add_admin(self):
        workspace = WorkspaceFactory()
        owner_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)
        target_user = UserFactory()

        membership = services.add_workspace_member(
            workspace=workspace,
            actor=owner_membership.user,
            actor_membership=owner_membership,
            email=target_user.email,
            role=WorkspaceRole.ADMIN,
        )
        assert membership.role == WorkspaceRole.ADMIN

    def test_admin_cannot_add_admin(self):
        workspace = WorkspaceFactory()
        admin_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.ADMIN)
        target_user = UserFactory()

        with pytest.raises(PermissionDenied):
            services.add_workspace_member(
                workspace=workspace,
                actor=admin_membership.user,
                actor_membership=admin_membership,
                email=target_user.email,
                role=WorkspaceRole.ADMIN,
            )

    def test_admin_can_add_support_manager(self):
        workspace = WorkspaceFactory()
        admin_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.ADMIN)
        target_user = UserFactory()

        membership = services.add_workspace_member(
            workspace=workspace,
            actor=admin_membership.user,
            actor_membership=admin_membership,
            email=target_user.email,
            role=WorkspaceRole.SUPPORT_MANAGER,
        )
        assert membership.role == WorkspaceRole.SUPPORT_MANAGER

    def test_nonexistent_account_gives_generic_error(self):
        workspace = WorkspaceFactory()
        owner_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)

        with pytest.raises(ValidationError) as exc_info:
            services.add_workspace_member(
                workspace=workspace,
                actor=owner_membership.user,
                actor_membership=owner_membership,
                email="nobody@example.com",
                role=WorkspaceRole.VIEWER,
            )
        assert "could not be added" in str(exc_info.value)

    def test_inactive_account_gives_generic_error(self):
        workspace = WorkspaceFactory()
        owner_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)
        inactive_user = UserFactory(is_active=False)

        with pytest.raises(ValidationError):
            services.add_workspace_member(
                workspace=workspace,
                actor=owner_membership.user,
                actor_membership=owner_membership,
                email=inactive_user.email,
                role=WorkspaceRole.VIEWER,
            )

    def test_duplicate_active_membership_is_a_conflict(self):
        workspace = WorkspaceFactory()
        owner_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)
        existing = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.VIEWER)

        with pytest.raises(ConflictError):
            services.add_workspace_member(
                workspace=workspace,
                actor=owner_membership.user,
                actor_membership=owner_membership,
                email=existing.user.email,
                role=WorkspaceRole.SUPPORT_AGENT,
            )

    def test_re_adding_an_inactive_member_reactivates_the_row(self):
        workspace = WorkspaceFactory()
        owner_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)
        removed = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.VIEWER, is_active=False
        )

        membership = services.add_workspace_member(
            workspace=workspace,
            actor=owner_membership.user,
            actor_membership=owner_membership,
            email=removed.user.email,
            role=WorkspaceRole.SUPPORT_AGENT,
        )

        assert membership.id == removed.id
        assert membership.is_active is True
        assert membership.role == WorkspaceRole.SUPPORT_AGENT
        assert (
            WorkspaceMembership.objects.filter(workspace=workspace, user=removed.user).count() == 1
        )

    def test_cannot_add_owner_role(self):
        workspace = WorkspaceFactory()
        owner_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)
        target_user = UserFactory()

        with pytest.raises(ValidationError):
            services.add_workspace_member(
                workspace=workspace,
                actor=owner_membership.user,
                actor_membership=owner_membership,
                email=target_user.email,
                role=WorkspaceRole.OWNER,
            )


@pytest.mark.django_db
class TestChangeWorkspaceMemberRole:
    def test_owner_promotes_agent_to_manager(self):
        workspace = WorkspaceFactory()
        owner_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)
        target = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)

        updated = services.change_workspace_member_role(
            workspace=workspace,
            actor=owner_membership.user,
            actor_membership=owner_membership,
            target_membership=target,
            new_role=WorkspaceRole.SUPPORT_MANAGER,
        )
        assert updated.role == WorkspaceRole.SUPPORT_MANAGER
        event = AuditEvent.objects.get(action="workspace.member_role_changed")
        assert event.metadata == {"old_role": "support_agent", "new_role": "support_manager"}

    def test_owner_promotes_manager_to_admin(self):
        workspace = WorkspaceFactory()
        owner_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)
        target = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_MANAGER)

        updated = services.change_workspace_member_role(
            workspace=workspace,
            actor=owner_membership.user,
            actor_membership=owner_membership,
            target_membership=target,
            new_role=WorkspaceRole.ADMIN,
        )
        assert updated.role == WorkspaceRole.ADMIN

    def test_admin_promotes_agent_to_manager(self):
        workspace = WorkspaceFactory()
        admin_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.ADMIN)
        target = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)

        updated = services.change_workspace_member_role(
            workspace=workspace,
            actor=admin_membership.user,
            actor_membership=admin_membership,
            target_membership=target,
            new_role=WorkspaceRole.SUPPORT_MANAGER,
        )
        assert updated.role == WorkspaceRole.SUPPORT_MANAGER

    def test_admin_cannot_promote_to_admin(self):
        workspace = WorkspaceFactory()
        admin_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.ADMIN)
        target = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)

        with pytest.raises(PermissionDenied):
            services.change_workspace_member_role(
                workspace=workspace,
                actor=admin_membership.user,
                actor_membership=admin_membership,
                target_membership=target,
                new_role=WorkspaceRole.ADMIN,
            )

    def test_admin_cannot_change_another_admin(self):
        workspace = WorkspaceFactory()
        admin_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.ADMIN)
        other_admin = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.ADMIN)

        with pytest.raises(PermissionDenied):
            services.change_workspace_member_role(
                workspace=workspace,
                actor=admin_membership.user,
                actor_membership=admin_membership,
                target_membership=other_admin,
                new_role=WorkspaceRole.SUPPORT_AGENT,
            )

    def test_target_from_another_workspace_is_rejected_at_the_service_layer(self):
        workspace = WorkspaceFactory()
        owner_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)
        foreign_target = WorkspaceMembershipFactory(workspace=WorkspaceFactory())

        with pytest.raises(ValidationError):
            services.change_workspace_member_role(
                workspace=workspace,
                actor=owner_membership.user,
                actor_membership=owner_membership,
                target_membership=foreign_target,
                new_role=WorkspaceRole.VIEWER,
            )

    def test_admin_cannot_change_owner(self):
        workspace = WorkspaceFactory()
        admin_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.ADMIN)
        owner = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)

        with pytest.raises(ValidationError):
            services.change_workspace_member_role(
                workspace=workspace,
                actor=admin_membership.user,
                actor_membership=admin_membership,
                target_membership=owner,
                new_role=WorkspaceRole.SUPPORT_AGENT,
            )

    def test_nobody_can_set_role_to_owner(self):
        workspace = WorkspaceFactory()
        owner_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)
        target = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)

        with pytest.raises(ValidationError):
            services.change_workspace_member_role(
                workspace=workspace,
                actor=owner_membership.user,
                actor_membership=owner_membership,
                target_membership=target,
                new_role=WorkspaceRole.OWNER,
            )

    def test_owner_role_cannot_be_downgraded_here(self):
        workspace = WorkspaceFactory()
        owner_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)

        with pytest.raises(ValidationError):
            services.change_workspace_member_role(
                workspace=workspace,
                actor=owner_membership.user,
                actor_membership=owner_membership,
                target_membership=owner_membership,
                new_role=WorkspaceRole.ADMIN,
            )

    @pytest.mark.parametrize(
        "caller_role",
        [WorkspaceRole.SUPPORT_MANAGER, WorkspaceRole.SUPPORT_AGENT, WorkspaceRole.VIEWER],
    )
    def test_non_admin_roles_cannot_change_roles(self, caller_role):
        workspace = WorkspaceFactory()
        caller_membership = WorkspaceMembershipFactory(workspace=workspace, role=caller_role)
        target = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)

        with pytest.raises(PermissionDenied):
            services.change_workspace_member_role(
                workspace=workspace,
                actor=caller_membership.user,
                actor_membership=caller_membership,
                target_membership=target,
                new_role=WorkspaceRole.SUPPORT_MANAGER,
            )


@pytest.mark.django_db
class TestRemoveWorkspaceMember:
    def test_owner_removes_lower_role(self):
        workspace = WorkspaceFactory()
        owner_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)
        target = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)

        services.remove_workspace_member(
            workspace=workspace,
            actor=owner_membership.user,
            actor_membership=owner_membership,
            target_membership=target,
        )
        target.refresh_from_db()
        assert target.is_active is False

    def test_target_from_another_workspace_is_rejected_at_the_service_layer(self):
        # Defense-in-depth: even if a caller bypasses the view's
        # workspace-scoped selector, the service itself must reject a
        # cross-tenant target rather than trust the caller.
        workspace = WorkspaceFactory()
        owner_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)
        foreign_target = WorkspaceMembershipFactory(workspace=WorkspaceFactory())

        with pytest.raises(ValidationError):
            services.remove_workspace_member(
                workspace=workspace,
                actor=owner_membership.user,
                actor_membership=owner_membership,
                target_membership=foreign_target,
            )

    def test_owner_removes_admin(self):
        workspace = WorkspaceFactory()
        owner_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)
        target = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.ADMIN)

        services.remove_workspace_member(
            workspace=workspace,
            actor=owner_membership.user,
            actor_membership=owner_membership,
            target_membership=target,
        )
        target.refresh_from_db()
        assert target.is_active is False

    def test_admin_removes_lower_role(self):
        workspace = WorkspaceFactory()
        admin_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.ADMIN)
        target = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.VIEWER)

        services.remove_workspace_member(
            workspace=workspace,
            actor=admin_membership.user,
            actor_membership=admin_membership,
            target_membership=target,
        )
        target.refresh_from_db()
        assert target.is_active is False

    def test_admin_cannot_remove_admin(self):
        workspace = WorkspaceFactory()
        admin_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.ADMIN)
        other_admin = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.ADMIN)

        with pytest.raises(PermissionDenied):
            services.remove_workspace_member(
                workspace=workspace,
                actor=admin_membership.user,
                actor_membership=admin_membership,
                target_membership=other_admin,
            )

    def test_admin_cannot_remove_owner(self):
        workspace = WorkspaceFactory()
        admin_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.ADMIN)
        owner = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)

        with pytest.raises(ValidationError):
            services.remove_workspace_member(
                workspace=workspace,
                actor=admin_membership.user,
                actor_membership=admin_membership,
                target_membership=owner,
            )

    def test_owner_cannot_remove_self(self):
        workspace = WorkspaceFactory()
        owner_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)

        with pytest.raises(ValidationError):
            services.remove_workspace_member(
                workspace=workspace,
                actor=owner_membership.user,
                actor_membership=owner_membership,
                target_membership=owner_membership,
            )

    @pytest.mark.parametrize(
        "caller_role",
        [WorkspaceRole.SUPPORT_MANAGER, WorkspaceRole.SUPPORT_AGENT, WorkspaceRole.VIEWER],
    )
    def test_non_admin_roles_cannot_remove_members(self, caller_role):
        workspace = WorkspaceFactory()
        caller_membership = WorkspaceMembershipFactory(workspace=workspace, role=caller_role)
        target = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.VIEWER)

        with pytest.raises(PermissionDenied):
            services.remove_workspace_member(
                workspace=workspace,
                actor=caller_membership.user,
                actor_membership=caller_membership,
                target_membership=target,
            )


@pytest.mark.django_db
class TestTransferWorkspaceOwnership:
    def test_transfers_ownership_and_demotes_previous_owner(self):
        workspace = WorkspaceFactory()
        owner_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)
        target = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.ADMIN)

        new_owner = services.transfer_workspace_ownership(
            workspace=workspace,
            actor=owner_membership.user,
            actor_membership=owner_membership,
            new_owner_membership=target,
        )

        new_owner.refresh_from_db()
        owner_membership.refresh_from_db()
        assert new_owner.role == WorkspaceRole.OWNER
        assert owner_membership.role == WorkspaceRole.ADMIN
        assert (
            WorkspaceMembership.objects.filter(
                workspace=workspace, role=WorkspaceRole.OWNER, is_active=True
            ).count()
            == 1
        )

    @pytest.mark.parametrize(
        "target_role",
        [
            WorkspaceRole.ADMIN,
            WorkspaceRole.SUPPORT_MANAGER,
            WorkspaceRole.SUPPORT_AGENT,
            WorkspaceRole.VIEWER,
        ],
    )
    def test_owner_can_transfer_to_any_active_member(self, target_role):
        workspace = WorkspaceFactory()
        owner_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)
        target = WorkspaceMembershipFactory(workspace=workspace, role=target_role)

        new_owner = services.transfer_workspace_ownership(
            workspace=workspace,
            actor=owner_membership.user,
            actor_membership=owner_membership,
            new_owner_membership=target,
        )
        assert new_owner.role == WorkspaceRole.OWNER

    def test_records_audit_event(self):
        workspace = WorkspaceFactory()
        owner_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)
        target = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.ADMIN)

        services.transfer_workspace_ownership(
            workspace=workspace,
            actor=owner_membership.user,
            actor_membership=owner_membership,
            new_owner_membership=target,
        )

        event = AuditEvent.objects.get(action="workspace.ownership_transferred")
        assert event.metadata == {
            "previous_owner_user_id": str(owner_membership.user_id),
            "new_owner_user_id": str(target.user_id),
        }

    def test_non_owner_cannot_transfer(self):
        workspace = WorkspaceFactory()
        admin_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.ADMIN)
        target = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)

        with pytest.raises(PermissionDenied):
            services.transfer_workspace_ownership(
                workspace=workspace,
                actor=admin_membership.user,
                actor_membership=admin_membership,
                new_owner_membership=target,
            )

    def test_target_from_another_workspace_is_rejected(self):
        workspace = WorkspaceFactory()
        owner_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)
        foreign_target = WorkspaceMembershipFactory(workspace=WorkspaceFactory())

        with pytest.raises(ValidationError):
            services.transfer_workspace_ownership(
                workspace=workspace,
                actor=owner_membership.user,
                actor_membership=owner_membership,
                new_owner_membership=foreign_target,
            )

    def test_inactive_target_is_rejected(self):
        workspace = WorkspaceFactory()
        owner_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)
        inactive_target = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.ADMIN, is_active=False
        )

        with pytest.raises(ValidationError):
            services.transfer_workspace_ownership(
                workspace=workspace,
                actor=owner_membership.user,
                actor_membership=owner_membership,
                new_owner_membership=inactive_target,
            )

    def test_target_deactivated_between_initial_check_and_row_lock_is_rejected(self):
        # Race-safety: the target was active when the caller loaded it, but
        # became inactive out-of-band before the transfer's row lock was
        # acquired. The post-lock re-check must still catch this.
        workspace = WorkspaceFactory()
        owner_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)
        target = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.ADMIN)
        WorkspaceMembership.objects.filter(pk=target.pk).update(is_active=False)
        # `target`'s in-memory `is_active` is still stale (True).

        with pytest.raises(ValidationError):
            services.transfer_workspace_ownership(
                workspace=workspace,
                actor=owner_membership.user,
                actor_membership=owner_membership,
                new_owner_membership=target,
            )

    def test_self_transfer_is_rejected(self):
        workspace = WorkspaceFactory()
        owner_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)

        with pytest.raises(ValidationError):
            services.transfer_workspace_ownership(
                workspace=workspace,
                actor=owner_membership.user,
                actor_membership=owner_membership,
                new_owner_membership=owner_membership,
            )

    def test_stale_repeated_transfer_fails_safely(self):
        workspace = WorkspaceFactory()
        owner_membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)
        target = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.ADMIN)

        services.transfer_workspace_ownership(
            workspace=workspace,
            actor=owner_membership.user,
            actor_membership=owner_membership,
            new_owner_membership=target,
        )

        # actor_membership (now demoted to admin) is stale: repeating the
        # same transfer must fail, not silently corrupt ownership state.
        with pytest.raises(ConflictError):
            services.transfer_workspace_ownership(
                workspace=workspace,
                actor=owner_membership.user,
                actor_membership=owner_membership,
                new_owner_membership=target,
            )

        assert (
            WorkspaceMembership.objects.filter(
                workspace=workspace, role=WorkspaceRole.OWNER, is_active=True
            ).count()
            == 1
        )
