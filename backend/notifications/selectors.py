"""Bounded, workspace-scoped read queries for the delivery domain (section 16).

No unbounded history API — attempt history is always limited, and every
delivery lookup is workspace-scoped so cross-workspace access resolves to
"not found" rather than leaking existence (section 22).
"""

from __future__ import annotations

import uuid

from django.db.models import QuerySet
from django.utils import timezone

from .models import (
    DELIVERY_DUE_CLAIMABLE_STATUSES,
    Delivery,
    DeliveryAttempt,
    DeliveryStatus,
)

MAX_ATTEMPT_HISTORY = 100


def due_claimable_deliveries(*, now=None) -> QuerySet[Delivery]:
    """PENDING/RETRY_SCHEDULED rows whose ``next_attempt_at`` has arrived —
    the future sweeper's (Block 4) candidate set. Not used to claim directly:
    a specific delivery id is always claimed through
    ``services.claim_delivery`` under its own row lock."""
    now = now or timezone.now()
    return Delivery.objects.filter(
        status__in=DELIVERY_DUE_CLAIMABLE_STATUSES, next_attempt_at__lte=now
    ).order_by("next_attempt_at", "created_at", "id")


def expired_claimed_deliveries(*, now=None) -> QuerySet[Delivery]:
    """CLAIMED rows whose lease has expired — the future reclaim sweeper's
    (Block 4) candidate set."""
    now = now or timezone.now()
    return Delivery.objects.filter(
        status=DeliveryStatus.CLAIMED, lease_expires_at__lte=now
    ).order_by("lease_expires_at", "created_at", "id")


def get_delivery_for_workspace(*, workspace_id, delivery_id: uuid.UUID | str) -> Delivery | None:
    """Workspace-scoped lookup. Returns ``None`` (never raises) for a
    delivery that belongs to another workspace or does not exist, so a
    caller can render the same "not found" outcome for both (section 22)."""
    return Delivery.objects.filter(pk=delivery_id, workspace_id=workspace_id).first()


def attempt_history(
    *, delivery: Delivery, limit: int = MAX_ATTEMPT_HISTORY
) -> QuerySet[DeliveryAttempt]:
    """Bounded, newest-first attempt history for one delivery."""
    limit = min(limit, MAX_ATTEMPT_HISTORY)
    return delivery.attempts.order_by("-attempt_number")[:limit]
