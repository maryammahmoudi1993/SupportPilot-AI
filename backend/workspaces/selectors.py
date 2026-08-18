"""Tenant-scoped read selectors.

Core rule for every function here: scope by tenant membership *before*
resolving a workspace-owned resource. Never fetch a globally-addressable
object first and then ask whether the caller may see it — that confirms
existence to a cross-tenant caller. A caller who is not an active member of
the workspace must get exactly the same `Http404` as a caller requesting a
workspace that does not exist at all.
"""

from __future__ import annotations

from uuid import UUID

from django.db.models import QuerySet
from django.http import Http404
from django.shortcuts import get_object_or_404

from accounts.models import User

from .models import Workspace, WorkspaceMembership


def list_workspaces_for_user(*, user: User) -> QuerySet[Workspace]:
    """Workspaces the user has an active membership in."""
    return (
        Workspace.objects.filter(
            memberships__user=user,
            memberships__is_active=True,
        )
        .distinct()
        .order_by("-created_at")
    )


def get_workspace_for_user_or_404(*, user: User, workspace_id: UUID | str) -> Workspace:
    """Resolve a workspace only if the user has an active membership in it.

    Raises Http404 for both "workspace does not exist" and "workspace exists
    but the user is not an active member" — the two cases are indistinguishable
    to the caller by design.
    """
    return get_object_or_404(
        Workspace.objects.filter(
            memberships__user=user,
            memberships__is_active=True,
        ).distinct(),
        pk=workspace_id,
    )


def get_active_membership(*, workspace: Workspace, user: User) -> WorkspaceMembership | None:
    """The user's active membership row for a workspace, or None."""
    return WorkspaceMembership.objects.filter(
        workspace=workspace, user=user, is_active=True
    ).first()


def get_membership(*, workspace: Workspace, user: User) -> WorkspaceMembership | None:
    """The user's membership row for a workspace regardless of active state."""
    return WorkspaceMembership.objects.filter(workspace=workspace, user=user).first()


def get_workspace_members(*, workspace: Workspace) -> QuerySet[WorkspaceMembership]:
    """Active memberships for a workspace, most senior/newest first."""
    return (
        WorkspaceMembership.objects.filter(workspace=workspace, is_active=True)
        .select_related("user")
        .order_by("-created_at")
    )


def get_workspace_member_or_404(
    *, workspace: Workspace, membership_id: UUID | str
) -> WorkspaceMembership:
    """Resolve a membership row scoped to a specific workspace.

    A membership ID belonging to a different workspace raises Http404, never a
    403 that would confirm the ID exists elsewhere.
    """
    membership = (
        WorkspaceMembership.objects.filter(pk=membership_id, workspace=workspace)
        .select_related("user")
        .first()
    )
    if membership is None:
        raise Http404("Membership not found.")
    return membership


def list_active_memberships_for_user(*, user: User) -> QuerySet[WorkspaceMembership]:
    """Active memberships for a user, with workspace pre-fetched — used by
    the current-user endpoint's workspace summary."""
    return (
        WorkspaceMembership.objects.filter(user=user, is_active=True)
        .select_related("workspace")
        .order_by("-created_at")
    )


def get_active_membership_for_workspace_id_or_none(
    *, user: User, workspace_id: UUID | str
) -> WorkspaceMembership | None:
    """Used by permission classes: the user's active membership for a workspace
    ID taken from the URL, without leaking whether the workspace itself exists."""
    return (
        WorkspaceMembership.objects.filter(workspace_id=workspace_id, user=user, is_active=True)
        .select_related("workspace")
        .first()
    )
