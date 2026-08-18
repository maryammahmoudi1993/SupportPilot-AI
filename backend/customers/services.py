"""Customer domain services.

Views resolve tenant-scoped objects via selectors, check permissions, and
delegate every state transition here. Serializers validate request *shape*
only.
"""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction

from accounts.models import User
from audit.models import AuditAction
from audit.services import record_event
from common.exceptions import ConflictError
from workspaces.models import Workspace

from .models import Customer

#: Fields a caller may set through the write API. ``workspace`` is always
#: derived server-side and is deliberately excluded.
WRITABLE_CUSTOMER_FIELDS = frozenset(
    {
        "external_id",
        "first_name",
        "last_name",
        "display_name",
        "email",
        "phone",
        "company",
        "notes",
        "metadata",
        "is_active",
    }
)


def _duplicate_external_id_error() -> ConflictError:
    return ConflictError("A customer with this external ID already exists in this workspace.")


@transaction.atomic
def create_customer(*, workspace: Workspace, data: dict[str, Any]) -> Customer:
    """Create a customer scoped to ``workspace``."""
    fields = {key: value for key, value in data.items() if key in WRITABLE_CUSTOMER_FIELDS}
    try:
        return Customer.objects.create(workspace=workspace, **fields)
    except IntegrityError as exc:
        raise _duplicate_external_id_error() from exc


@transaction.atomic
def update_customer(
    *,
    workspace: Workspace,
    customer: Customer,
    actor: User,
    data: dict[str, Any],
    request_id: str | None = None,
) -> Customer:
    """Apply a partial update. Deactivation (``is_active`` False -> transition)
    is recorded in the audit trail; other field edits are routine operational
    updates and are not individually audited."""
    was_active = customer.is_active
    for field in WRITABLE_CUSTOMER_FIELDS:
        if field in data:
            setattr(customer, field, data[field])

    try:
        customer.save()
    except IntegrityError as exc:
        raise _duplicate_external_id_error() from exc

    if was_active and not customer.is_active:
        record_event(
            action=AuditAction.CUSTOMER_DEACTIVATED,
            target_type="customer",
            target_id=customer.id,
            actor=actor,
            workspace=workspace,
            metadata={"customer_id": str(customer.id)},
            request_id=request_id,
        )
    return customer


@transaction.atomic
def deactivate_customer(
    *,
    workspace: Workspace,
    customer: Customer,
    actor: User,
    request_id: str | None = None,
) -> Customer:
    """Controlled deactivation — history is preserved rather than deleted."""
    return update_customer(
        workspace=workspace,
        customer=customer,
        actor=actor,
        data={"is_active": False},
        request_id=request_id,
    )
