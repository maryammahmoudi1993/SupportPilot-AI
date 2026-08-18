"""Tests for accounts serializers."""

import pytest

from accounts.serializers import LoginRequestSerializer, MeSerializer, UserSerializer
from accounts.tests.factories import UserFactory
from workspaces.tests.factories import WorkspaceMembershipFactory


@pytest.mark.django_db
class TestUserSerializer:
    def test_serializes_expected_fields_only(self):
        user = UserFactory(email="jane@example.com")
        data = UserSerializer(user).data
        assert set(data.keys()) == {"id", "email", "first_name", "last_name", "is_active"}
        assert data["email"] == "jane@example.com"

    def test_password_is_never_serialized(self):
        user = UserFactory()
        assert "password" not in UserSerializer(user).data


class TestLoginRequestSerializer:
    def test_requires_email_and_password(self):
        serializer = LoginRequestSerializer(data={})
        assert not serializer.is_valid()
        assert "email" in serializer.errors
        assert "password" in serializer.errors

    def test_rejects_an_invalid_email(self):
        serializer = LoginRequestSerializer(data={"email": "not-an-email", "password": "x"})
        assert not serializer.is_valid()


@pytest.mark.django_db
class TestMeSerializer:
    def test_includes_safe_fields_and_workspace_summary(self):
        membership = WorkspaceMembershipFactory()
        data = MeSerializer(membership.user).data

        assert data["email"] == membership.user.email
        assert "password" not in data
        assert data["workspaces"] == [
            {
                "id": str(membership.workspace_id),
                "name": membership.workspace.name,
                "slug": membership.workspace.slug,
                "role": membership.role,
            }
        ]

    def test_display_name_falls_back_to_email(self):
        user = UserFactory(email="noname@example.com", first_name="", last_name="")
        data = MeSerializer(user).data
        assert data["display_name"] == "noname@example.com"

    def test_inactive_memberships_are_excluded(self):
        membership = WorkspaceMembershipFactory(is_active=False)
        data = MeSerializer(membership.user).data
        assert data["workspaces"] == []
