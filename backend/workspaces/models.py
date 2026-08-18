"""Workspace tenancy models.

``Workspace`` is the tenant boundary for the whole platform. ``WorkspaceMembership``
is the sole source of truth for a user's authorization within a workspace — role
claims from JWTs, headers, or client state are never authoritative (see
``workspaces/selectors.py`` and ``workspaces/permissions.py``).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.text import slugify

from common.models import BaseModel


class WorkspaceRole(models.TextChoices):
    """Explicit, non-hierarchical role enum.

    Authorization is implemented as explicit capability checks per role
    (see ``workspaces/permissions.py``), never as a numeric role comparison.
    """

    OWNER = "owner", "Owner"
    ADMIN = "admin", "Admin"
    SUPPORT_MANAGER = "support_manager", "Support Manager"
    SUPPORT_AGENT = "support_agent", "Support Agent"
    VIEWER = "viewer", "Viewer"


class Workspace(BaseModel):
    """A tenant. The UUID primary key (from ``BaseModel``) is the security-safe
    identifier; the slug is a display/navigation convenience and is never treated
    as secret or as an authorization boundary."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(name=""),
                name="workspace_name_not_blank",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        self.name = " ".join(self.name.split()) if self.name else self.name
        if not self.slug:
            self.slug = slugify(self.name)[:220] or None
        super().save(*args, **kwargs)


class WorkspaceMembership(BaseModel):
    """A user's role within a workspace. The authoritative source of truth for
    workspace authorization — always re-derived from the database on every
    workspace-scoped request, never trusted from client-supplied claims."""

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workspace_memberships"
    )
    role = models.CharField(max_length=32, choices=WorkspaceRole.choices)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user"],
                name="uniq_member_workspace_user",
            ),
            # Database-enforced invariant: at most one *active* owner per
            # workspace. The complementary invariant (never zero owners after
            # any supported operation) is enforced transactionally in the
            # service layer, since the database cannot express "never empty".
            models.UniqueConstraint(
                fields=["workspace"],
                condition=models.Q(role=WorkspaceRole.OWNER, is_active=True),
                name="uniq_active_owner_per_ws",
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "user"], name="ws_member_wu_idx"),
            models.Index(fields=["workspace", "is_active"], name="ws_member_wa_idx"),
            models.Index(fields=["user", "is_active"], name="ws_member_ua_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} @ {self.workspace_id} ({self.role})"
