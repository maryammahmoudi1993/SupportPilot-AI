"""Audit write path. This is the only supported way to create an AuditEvent —
there is deliberately no update/delete service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from accounts.models import User

from .models import AuditAction, AuditEvent

if TYPE_CHECKING:
    from workspaces.models import Workspace


def record_event(
    *,
    action: AuditAction | str,
    target_type: str,
    target_id: str | UUID,
    actor: User | None = None,
    workspace: Workspace | None = None,
    metadata: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> AuditEvent:
    """Persist one audit event.

    Callers performing a mutation that must be atomic with its audit trail
    (workspace/member administration) should call this inside the same
    ``transaction.atomic()`` block as the mutation itself.
    """
    return AuditEvent.objects.create(
        workspace=workspace,
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        metadata=metadata or {},
        request_id=request_id,
    )
