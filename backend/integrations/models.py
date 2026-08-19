"""Workspace-scoped external business integrations.

``IntegrationConnection`` is the only place a workspace's provider
credentials live. Credentials are always stored encrypted
(``encrypted_credentials`` — see ``integrations.crypto``); nothing in this
module, its serializers, or its admin representation ever exposes plaintext
(section 11-18 of the Phase 7 brief).

Exactly one connection may exist per (workspace, provider): section 71 opts
into "one active connection per provider", enforced by a database
constraint rather than left to application-level convention.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from common.models import BaseModel


class IntegrationProvider(models.TextChoices):
    """Server-owned provider identifiers. Never database/model-created —
    the provider factory (``integrations.providers.factory``) only ever
    dispatches on one of these (section 139-140)."""

    STRIPE = "stripe", "Stripe"
    GOOGLE_CALENDAR = "google_calendar", "Google Calendar"
    EMAIL = "email", "Email notifications"
    DEMO_COMMERCE = "demo_commerce", "Demo commerce (orders & shipments)"


class IntegrationEnvironment(models.TextChoices):
    """Explicit sandbox/production distinction (section 37). Phase 7 never
    requires or exercises ``LIVE`` — see ``INTEGRATIONS_LIVE_PROVIDERS_ENABLED``."""

    TEST = "test", "Test / sandbox"
    LIVE = "live", "Live / production"


class IntegrationConnectionStatus(models.TextChoices):
    """Explicit lifecycle — never an ambiguous boolean (section 12)."""

    ACTIVE = "active", "Active"
    DISABLED = "disabled", "Disabled"
    INVALID_CREDENTIALS = "invalid_credentials", "Invalid credentials"
    DEGRADED = "degraded", "Degraded"


#: Safe, server-derived capability identifiers a connection may advertise.
#: Never trusted from client input (section 113) — always derived from
#: ``provider`` by ``integrations.selectors.capabilities_for_provider``.
PROVIDER_CAPABILITIES: dict[str, frozenset[str]] = {
    IntegrationProvider.STRIPE: frozenset({"payment_lookup", "refund"}),
    IntegrationProvider.GOOGLE_CALENDAR: frozenset({"calendar_availability", "calendar_booking"}),
    IntegrationProvider.EMAIL: frozenset({"notification_send"}),
    IntegrationProvider.DEMO_COMMERCE: frozenset({"order_lookup", "shipment_lookup"}),
}


class IntegrationConnection(BaseModel):
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="integration_connections"
    )
    provider = models.CharField(max_length=32, choices=IntegrationProvider.choices)
    display_name = models.CharField(max_length=200, blank=True)
    status = models.CharField(
        max_length=20,
        choices=IntegrationConnectionStatus.choices,
        default=IntegrationConnectionStatus.DISABLED,
    )
    environment = models.CharField(
        max_length=8, choices=IntegrationEnvironment.choices, default=IntegrationEnvironment.TEST
    )

    # Versioned encrypted credential envelope (Fernet token — see
    # integrations/crypto.py). Blank until credentials are first submitted.
    # Never exposed through any serializer (section 17).
    encrypted_credentials = models.TextField(blank=True)
    credential_version = models.PositiveIntegerField(default=0)

    # Non-secret provider configuration only (e.g. calendar_id, from_email).
    # Validated per-provider before save — see ``integrations.services``.
    configuration = models.JSONField(default=dict, blank=True)

    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=64, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_integration_connections",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "provider"], name="uniq_integration_conn_ws_provider"
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "status"], name="integ_conn_ws_status_idx"),
        ]

    def __str__(self) -> str:
        # Deliberately excludes credential material — safe even in shells/logs.
        return f"{self.workspace_id}:{self.provider}:{self.status}"

    @property
    def enabled(self) -> bool:
        return self.status == IntegrationConnectionStatus.ACTIVE

    @property
    def credentials_configured(self) -> bool:
        return bool(self.encrypted_credentials)

    @property
    def capabilities(self) -> frozenset[str]:
        return PROVIDER_CAPABILITIES.get(self.provider, frozenset())
