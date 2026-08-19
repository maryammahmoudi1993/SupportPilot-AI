"""Tenant-scoped read selectors for customers.

Every function here scopes by workspace *before* resolving a specific
customer, so a foreign-workspace customer ID behaves exactly like an ID
that does not exist at all.
"""

from __future__ import annotations

from uuid import UUID

from django.db.models import Q, QuerySet
from django.http import Http404

from workspaces.models import Workspace

from .models import Customer


def customer_list_for_workspace(
    *,
    workspace: Workspace,
    search: str | None = None,
    is_active: bool | None = None,
) -> QuerySet[Customer]:
    """Workspace-scoped, optionally filtered customer queryset."""
    qs = Customer.objects.filter(workspace=workspace)
    if is_active is not None:
        qs = qs.filter(is_active=is_active)
    if search:
        qs = qs.filter(
            Q(display_name__icontains=search)
            | Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(email__icontains=search)
            | Q(phone__icontains=search)
            | Q(external_id__icontains=search)
        )
    return qs.order_by("-created_at")


def customer_get_for_workspace_or_404(*, workspace: Workspace, customer_id: UUID | str) -> Customer:
    """Resolve a customer scoped to a specific workspace.

    A customer ID belonging to a different workspace raises Http404, never a
    403 that would confirm the ID exists elsewhere.
    """
    customer = Customer.objects.filter(workspace=workspace, pk=customer_id).first()
    if customer is None:
        raise Http404("Customer not found.")
    return customer


def customer_get_by_id_for_workspace(*, workspace: Workspace, customer_id: str) -> Customer | None:
    """Like ``customer_get_for_workspace_or_404`` but returns ``None``
    instead of raising — used by tool handlers (integrations.tools) that
    normalize "not found" into their own stable error code rather than an
    HTTP concern."""
    if not customer_id:
        return None
    try:
        UUID(str(customer_id))
    except (ValueError, AttributeError):
        return None
    return Customer.objects.filter(workspace=workspace, pk=customer_id).first()


def customer_get_by_email_for_workspace(*, workspace: Workspace, email: str) -> Customer | None:
    return Customer.objects.filter(workspace=workspace, email=email.strip().lower()).first()


def customer_get_by_external_id_for_workspace(
    *, workspace: Workspace, external_id: str
) -> Customer | None:
    return Customer.objects.filter(workspace=workspace, external_id=external_id).first()
