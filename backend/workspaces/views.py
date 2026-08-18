"""Workspace and membership views.

Thin by design: every view resolves tenant-scoped objects through
``workspaces.selectors``, checks a capability-based permission, and
delegates the actual state transition to ``workspaces.services``.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import NotAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import selectors, services
from .models import Workspace, WorkspaceMembership
from .permissions import CanManageMembers, CanManageWorkspace, IsWorkspaceMember, IsWorkspaceOwner
from .serializers import (
    MemberAddSerializer,
    MemberRoleUpdateSerializer,
    OwnershipTransferSerializer,
    WorkspaceCreateSerializer,
    WorkspaceMembershipSerializer,
    WorkspaceSerializer,
    WorkspaceUpdateSerializer,
)


def _request_id(request) -> str | None:
    return getattr(request, "request_id", None)


class WorkspaceScopedMixin:
    """Resolves ``self.workspace`` and ``self.membership`` (the caller's own
    active membership) from the ``workspace_id`` URL kwarg *inside*
    ``check_permissions`` — after authentication has run, but before any
    workspace-specific permission class runs. Anonymous callers get 401.
    Callers who are not an active member of the workspace get 404, exactly
    as if the workspace did not exist, so cross-tenant lookups never confirm
    existence.
    """

    def check_permissions(self, request):
        if not (request.user and request.user.is_authenticated):
            raise NotAuthenticated()

        self.workspace = selectors.get_workspace_for_user_or_404(
            user=request.user, workspace_id=self.kwargs["workspace_id"]
        )
        self.membership = selectors.get_active_membership(
            workspace=self.workspace, user=request.user
        )
        request.workspace = self.workspace
        request.workspace_membership = self.membership
        super().check_permissions(request)


class WorkspaceListCreateView(generics.ListCreateAPIView):
    """GET: workspaces the caller is an active member of. POST: create a new
    workspace with the caller as its sole owner."""

    queryset = Workspace.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Workspace.objects.none()
        return selectors.list_workspaces_for_user(user=self.request.user)

    def get_serializer_class(self):
        if self.request.method == "POST":
            return WorkspaceCreateSerializer
        return WorkspaceSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        workspace = services.create_workspace(
            actor=request.user,
            name=serializer.validated_data["name"],
            request_id=_request_id(request),
        )
        return Response(WorkspaceSerializer(workspace).data, status=status.HTTP_201_CREATED)


class WorkspaceDetailView(WorkspaceScopedMixin, APIView):
    """GET: any active member. PATCH: owner/admin only."""

    def get_permissions(self):
        if self.request.method in {"PATCH", "PUT"}:
            return [IsWorkspaceMember(), CanManageWorkspace()]
        return [IsWorkspaceMember()]

    @extend_schema(responses=WorkspaceSerializer)
    def get(self, request, workspace_id):
        return Response(WorkspaceSerializer(self.workspace).data)

    @extend_schema(request=WorkspaceUpdateSerializer, responses=WorkspaceSerializer)
    def patch(self, request, workspace_id):
        serializer = WorkspaceUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        workspace = services.update_workspace(
            workspace=self.workspace,
            actor=request.user,
            name=serializer.validated_data.get("name"),
            request_id=_request_id(request),
        )
        return Response(WorkspaceSerializer(workspace).data)


class WorkspaceMemberListCreateView(WorkspaceScopedMixin, generics.ListCreateAPIView):
    """GET: any active member may list members. POST: owner/admin only."""

    serializer_class = WorkspaceMembershipSerializer
    queryset = WorkspaceMembership.objects.none()

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsWorkspaceMember(), CanManageMembers()]
        return [IsWorkspaceMember()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return WorkspaceMembership.objects.none()
        return selectors.get_workspace_members(workspace=self.workspace)

    def create(self, request, *args, **kwargs):
        serializer = MemberAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = services.add_workspace_member(
            workspace=self.workspace,
            actor=request.user,
            actor_membership=self.membership,
            email=serializer.validated_data["email"],
            role=serializer.validated_data["role"],
            request_id=_request_id(request),
        )
        return Response(
            WorkspaceMembershipSerializer(membership).data, status=status.HTTP_201_CREATED
        )


class WorkspaceMemberDetailView(WorkspaceScopedMixin, APIView):
    """GET: any active member. PATCH (role change) / DELETE (remove):
    owner/admin only, per the capability matrix enforced in the service
    layer."""

    def get_permissions(self):
        if self.request.method in {"PATCH", "PUT", "DELETE"}:
            return [IsWorkspaceMember(), CanManageMembers()]
        return [IsWorkspaceMember()]

    @extend_schema(responses=WorkspaceMembershipSerializer)
    def get(self, request, workspace_id, membership_id):
        member = selectors.get_workspace_member_or_404(
            workspace=self.workspace, membership_id=membership_id
        )
        return Response(WorkspaceMembershipSerializer(member).data)

    @extend_schema(request=MemberRoleUpdateSerializer, responses=WorkspaceMembershipSerializer)
    def patch(self, request, workspace_id, membership_id):
        target = selectors.get_workspace_member_or_404(
            workspace=self.workspace, membership_id=membership_id
        )
        serializer = MemberRoleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = services.change_workspace_member_role(
            workspace=self.workspace,
            actor=request.user,
            actor_membership=self.membership,
            target_membership=target,
            new_role=serializer.validated_data["role"],
            request_id=_request_id(request),
        )
        return Response(WorkspaceMembershipSerializer(membership).data)

    @extend_schema(responses={204: OpenApiResponse(description="Member removed.")})
    def delete(self, request, workspace_id, membership_id):
        target = selectors.get_workspace_member_or_404(
            workspace=self.workspace, membership_id=membership_id
        )
        services.remove_workspace_member(
            workspace=self.workspace,
            actor=request.user,
            actor_membership=self.membership,
            target_membership=target,
            request_id=_request_id(request),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkspaceOwnershipTransferView(WorkspaceScopedMixin, APIView):
    """POST: owner-only. Atomically hands ownership to another active member
    and demotes the current owner to admin."""

    def get_permissions(self):
        return [IsWorkspaceMember(), IsWorkspaceOwner()]

    @extend_schema(request=OwnershipTransferSerializer, responses=WorkspaceMembershipSerializer)
    def post(self, request, workspace_id):
        serializer = OwnershipTransferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target = selectors.get_workspace_member_or_404(
            workspace=self.workspace, membership_id=serializer.validated_data["membership_id"]
        )
        membership = services.transfer_workspace_ownership(
            workspace=self.workspace,
            actor=request.user,
            actor_membership=self.membership,
            new_owner_membership=target,
            request_id=_request_id(request),
        )
        return Response(WorkspaceMembershipSerializer(membership).data)
