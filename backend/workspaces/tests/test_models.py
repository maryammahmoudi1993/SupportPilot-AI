"""Model-level tests: normalization, constraints, and invariants."""

import pytest
from django.db import IntegrityError, transaction

from workspaces.models import Workspace, WorkspaceMembership, WorkspaceRole

from .factories import UserFactory, WorkspaceFactory, WorkspaceMembershipFactory


@pytest.mark.django_db
class TestWorkspaceModel:
    def test_string_representation_is_the_name(self):
        workspace = WorkspaceFactory(name="Acme Support")
        assert str(workspace) == "Acme Support"

    def test_name_is_whitespace_normalized_on_save(self):
        workspace = Workspace.objects.create(name="  Acme   Support  ")
        assert workspace.name == "Acme Support"

    def test_slug_is_derived_from_name_when_not_supplied(self):
        workspace = Workspace.objects.create(name="Acme Support")
        assert workspace.slug == "acme-support"

    def test_blank_name_is_rejected_by_database_constraint(self):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Workspace.objects.create(name="", slug="blank")

    def test_slug_is_unique(self):
        Workspace.objects.create(name="Acme", slug="acme")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Workspace.objects.create(name="Acme Two", slug="acme")


@pytest.mark.django_db
class TestWorkspaceMembershipModel:
    def test_string_representation(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.SUPPORT_AGENT)
        assert str(membership.user_id) in str(membership)
        assert "support_agent" in str(membership)

    def test_role_must_be_a_valid_choice(self):
        from django.core.exceptions import ValidationError as DjangoValidationError

        workspace = WorkspaceFactory()
        user = UserFactory()
        membership = WorkspaceMembership(workspace=workspace, user=user, role="not-a-role")
        with pytest.raises(DjangoValidationError):
            membership.full_clean()

    def test_user_can_have_at_most_one_membership_per_workspace(self):
        workspace = WorkspaceFactory()
        user = UserFactory()
        WorkspaceMembershipFactory(workspace=workspace, user=user)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                WorkspaceMembershipFactory(workspace=workspace, user=user)

    def test_workspace_can_have_at_most_one_active_owner(self):
        workspace = WorkspaceFactory()
        WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)

    def test_inactive_owner_does_not_block_a_new_active_owner(self):
        workspace = WorkspaceFactory()
        first_owner = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)
        first_owner.is_active = False
        first_owner.save(update_fields=["is_active"])

        # A second, active owner row is permitted once the first is inactive —
        # the conditional unique constraint only guards *active* owners.
        second_owner = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)
        assert second_owner.is_active is True

    def test_inactive_membership_grants_no_authorization_by_convention(self):
        # Enforced by the selectors/permissions layer, but the model itself
        # must allow the state to exist so removal/deactivation is possible.
        membership = WorkspaceMembershipFactory(is_active=False)
        assert membership.is_active is False
