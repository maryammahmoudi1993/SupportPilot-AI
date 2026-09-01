"""Customer identity resolution (Phase 13 section 27-28).

The one service responsible for converting a canonical channel identity into
a workspace-scoped ``Customer`` — every adapter/view calls this, never its
own ad hoc lookup (section 27). Deterministic by construction: identity is
always resolved through the single ``Customer.external_id`` key namespaced
by channel (``f"{channel}:{external_identity}"``), never a bare, potentially
multi-match email search — so "ambiguous identity" (section 27) cannot occur
through this path at all, and "unsafe automatic account linking" (section
25) is structurally impossible: a new inbound identity can only ever create
or reuse *its own* namespaced record, never silently attach to an existing
customer created some other way.
"""

from __future__ import annotations

from customers.models import Customer
from customers.selectors import customer_get_by_external_id_for_workspace
from customers.services import create_customer
from workspaces.models import Workspace

from .errors import IdentityNotFoundError
from .models import ChannelEndpoint, ChannelType, UnknownCustomerPolicy
from .schemas import CanonicalInboundMessage


def channel_identity_key(*, channel: str, external_identity: str) -> str:
    """The namespaced ``Customer.external_id`` value a channel identity maps
    to (section 29): namespacing by channel keeps the same raw external
    identity string from two different channels from ever colliding on one
    customer record by accident."""
    return f"{channel}:{external_identity}"[:255]


def resolve_customer_identity(
    *, workspace: Workspace, endpoint: ChannelEndpoint, canonical: CanonicalInboundMessage
) -> Customer:
    """Resolve (or, per ``endpoint.unknown_customer_policy``, create) the
    ``Customer`` this inbound message belongs to.

    Deliberately does not distinguish "inactive" as a separate outcome
    (section 27's "inactive customer" case): an inactive customer is still
    *this* customer — deactivation controls staff-facing customer-management
    behavior (``customers.services.deactivate_customer``), not whether a
    channel may keep routing a real customer's messages into their existing
    conversation history. Rejecting inbound messages from a customer a
    workspace has deactivated would silently drop real customer content,
    which is a worse outcome than the deactivation feature was ever meant to
    cause.
    """
    external_id = channel_identity_key(
        channel=endpoint.channel, external_identity=canonical.external_identity
    )
    existing = customer_get_by_external_id_for_workspace(
        workspace=workspace, external_id=external_id
    )
    if existing is not None:
        return existing

    if endpoint.unknown_customer_policy == UnknownCustomerPolicy.REJECT:
        raise IdentityNotFoundError()

    return create_customer(
        workspace=workspace,
        data={
            "external_id": external_id,
            "email": canonical.external_identity if endpoint.channel == ChannelType.EMAIL else None,
            "display_name": canonical.external_identity,
        },
    )
