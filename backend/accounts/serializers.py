"""Accounts serializers."""

from __future__ import annotations

from rest_framework import serializers

from .models import User


class UserSerializer(serializers.ModelSerializer):
    """Safe, minimal user representation. Never includes password/hashes."""

    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "is_active"]
        read_only_fields = fields


class LoginRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(trim_whitespace=False, style={"input_type": "password"})


class WorkspaceMembershipSummarySerializer(serializers.Serializer):
    """One workspace-membership row as shown on the current-user endpoint."""

    id = serializers.SerializerMethodField()
    name = serializers.CharField(source="workspace.name")
    slug = serializers.CharField(source="workspace.slug")
    role = serializers.CharField()

    def get_id(self, membership) -> str:
        return str(membership.workspace_id)


class MeSerializer(serializers.Serializer):
    """Current-user response: safe account fields plus a workspace-membership
    summary. Never includes a client-authoritative ``active_workspace_role``
    — workspace role is always re-derived per-request from the database."""

    id = serializers.IntegerField()
    email = serializers.EmailField()
    display_name = serializers.SerializerMethodField()
    workspaces = serializers.SerializerMethodField()

    def get_display_name(self, user: User) -> str:
        return user.get_full_name() or user.email

    def get_workspaces(self, user: User) -> list[dict]:
        from workspaces.selectors import list_active_memberships_for_user

        memberships = list_active_memberships_for_user(user=user)
        # drf-stubs sometimes infers `.data` as ReturnDict here despite
        # `many=True`; it is a ReturnList (list-like) at runtime.
        return list(WorkspaceMembershipSummarySerializer(memberships, many=True).data)


class LoginSuccessSerializer(serializers.Serializer):
    """Response shape for a successful login. The refresh token is never
    included here — it is only ever set as an HttpOnly cookie."""

    access = serializers.CharField()
    user = MeSerializer()
