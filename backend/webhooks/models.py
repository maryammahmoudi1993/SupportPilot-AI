"""Outbound webhook domain models (Phase 10 Block 3).

``WebhookEndpoint`` is workspace-scoped destination configuration.
``WebhookEvent`` is an immutable, safe-fields-only snapshot of one domain
occurrence — never a live reference to mutable business state (section 8).
``WebhookDelivery`` is the one-to-one link between a Block 1 ``Delivery``
and the specific (endpoint, event) pair it is delivering; the DB-unique
constraint on that pair is the fanout dedup invariant (section 10).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from common.models import BaseModel


class WebhookEndpointStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    DISABLED = "disabled", "Disabled"


class WebhookEventType(models.TextChoices):
    """Server-owned allowlist (section 6, 39) — never an arbitrary
    client-supplied string. Deliberately a small starting set (section 47):
    the four approval-lifecycle outcomes plus human-handoff creation, all
    already safe-by-design structured domain events with an existing
    service-layer call site to hook into."""

    APPROVAL_REQUESTED = "approval.requested", "Approval requested"
    APPROVAL_APPROVED = "approval.approved", "Approval approved"
    APPROVAL_REJECTED = "approval.rejected", "Approval rejected"
    APPROVAL_EXPIRED = "approval.expired", "Approval expired"
    HANDOFF_CREATED = "handoff.created", "Human handoff created"


class WebhookEndpoint(BaseModel):
    """A workspace-owned outbound webhook destination. Never stores a
    plaintext signing secret (section 12) — only the encrypted envelope,
    reusing ``integrations.crypto`` unchanged rather than a second
    encryption implementation."""

    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="webhook_endpoints"
    )
    name = models.CharField(max_length=200)
    url = models.CharField(max_length=2048)
    status = models.CharField(
        max_length=20, choices=WebhookEndpointStatus.choices, default=WebhookEndpointStatus.ACTIVE
    )
    # Server-validated against WebhookEventType at write time (section 39)
    # — a JSONField list rather than Postgres ArrayField, matching this
    # repository's existing convention for small structured lists (e.g.
    # ``policies.PolicyRule.condition_config``) over a Postgres-specific
    # column type nothing else in the project currently uses.
    subscribed_event_types = models.JSONField(default=list, blank=True)

    # Versioned encrypted secret envelope (Fernet token via
    # ``integrations.crypto``, section 12) — blank until a secret has been
    # generated. Never exposed through any serializer.
    encrypted_signing_secret = models.TextField(blank=True)
    secret_created_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="webhook_endpoints_created",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(name=""), name="webhook_endpoint_name_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(url=""), name="webhook_endpoint_url_not_blank"
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "status"], name="webhook_ep_ws_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.id}:{self.name}:{self.status}"

    @property
    def secret_configured(self) -> bool:
        return bool(self.encrypted_signing_secret)


class WebhookEvent(BaseModel):
    """One immutable domain occurrence. ``payload_snapshot`` is the safe
    ``data`` portion of the versioned envelope only (section 7-8) — the
    envelope's ``id``/``created_at`` are this row's own primary key and
    creation timestamp, never duplicated into the JSON blob, so there is
    exactly one source of truth for them."""

    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="webhook_events"
    )
    event_type = models.CharField(max_length=64, choices=WebhookEventType.choices)
    version = models.PositiveIntegerField(default=1)
    payload_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(version__gt=0), name="webhook_event_version_gt_0"
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "-created_at"], name="webhook_evt_ws_created_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.id}:{self.event_type}:v{self.version}"


class WebhookDelivery(BaseModel):
    """The one-to-one link between a Block 1 ``Delivery`` and exactly one
    (endpoint, event) pair. Never carries its own status/attempt fields —
    ``delivery`` is the single source of truth for lifecycle state
    (section 4)."""

    delivery = models.OneToOneField(
        "notifications.Delivery", on_delete=models.CASCADE, related_name="webhook_delivery"
    )
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="webhook_deliveries"
    )
    endpoint = models.ForeignKey(
        WebhookEndpoint, on_delete=models.PROTECT, related_name="deliveries"
    )
    event = models.ForeignKey(WebhookEvent, on_delete=models.PROTECT, related_name="deliveries")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # DB-enforced fanout dedup (section 10): one logical delivery
            # per (endpoint, event) pair, regardless of how many times
            # event production is retried/replayed.
            models.UniqueConstraint(
                fields=["endpoint", "event"], name="webhook_delivery_endpoint_event_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "-created_at"], name="webhook_dlv_ws_created_idx"),
            models.Index(fields=["endpoint", "-created_at"], name="webhook_dlv_ep_created_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.delivery_id}:{self.endpoint_id}:{self.event_id}"
