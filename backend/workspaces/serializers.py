"""Workspace serializers.

Serializers validate request *shape* only. Transactional business rules
(ownership invariants, role-management capability, audit) live in
``workspaces/services.py`` — never here.
"""

from __future__ import annotations

from rest_framework import serializers

from accounts.models import User

from .models import Workspace, WorkspaceMembership, WorkspaceRole

# Roles assignable through the generic member-management endpoints. `owner`
# is deliberately excluded — it can only change via dedicated ownership
# transfer.
ASSIGNABLE_ROLES = [
    WorkspaceRole.ADMIN,
    WorkspaceRole.SUPPORT_MANAGER,
    WorkspaceRole.SUPPORT_AGENT,
    WorkspaceRole.VIEWER,
]


class WorkspaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Workspace
        fields = ["id", "name", "slug", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "slug", "is_active", "created_at", "updated_at"]


class WorkspaceCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)


class WorkspaceUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200, required=False)


class MembershipUserSerializer(serializers.Serializer):
    """Minimal, safe user representation nested under a membership."""

    id = serializers.IntegerField()
    email = serializers.EmailField()
    display_name = serializers.SerializerMethodField()

    def get_display_name(self, user: User) -> str:
        return user.get_full_name() or user.email


class WorkspaceMembershipSerializer(serializers.ModelSerializer):
    user = MembershipUserSerializer(read_only=True)

    class Meta:
        model = WorkspaceMembership
        fields = ["id", "user", "role", "is_active", "created_at", "updated_at"]
        read_only_fields = fields


class MemberAddSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=[r.value for r in ASSIGNABLE_ROLES])


class MemberRoleUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=[r.value for r in ASSIGNABLE_ROLES])


class OwnershipTransferSerializer(serializers.Serializer):
    membership_id = serializers.UUIDField()
