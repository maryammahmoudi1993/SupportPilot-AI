"""Channel endpoint configuration management (Phase 13 section 15, 44, 46).

Mirrors ``webhooks.services``' endpoint-management functions closely — same
create/rotate-secret-once/audit shape — applied to ``ChannelEndpoint``
instead of ``WebhookEndpoint``. Every mutation here is workspace-scoped and
audited; there is no direct-field-write path from any serializer.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from agents.models import AgentVersion, AgentVersionStatus
from audit.models import AuditAction
from audit.services import record_event
from integrations.crypto import encrypt_credentials
from webhooks.signing import generate_signing_secret

from .models import ChannelEndpoint, ChannelEndpointStatus, ChannelType, UnknownCustomerPolicy

MAX_NAME_LENGTH = 200


class InvalidAgentVersionError(ValueError):
    """Raised when the requested agent version cannot back a channel
    endpoint: it must belong to the same workspace and be published (the
    same invariant ``agents.orchestration.start_support_agent_run`` enforces
    at run time — checked here too so a misconfigured endpoint fails at
    creation, not silently at the first inbound message)."""


def _validate_agent_version(*, workspace, agent_version: AgentVersion) -> None:
    if agent_version.agent_definition.workspace_id != workspace.id:
        raise InvalidAgentVersionError("Agent version does not belong to this workspace.")
    if agent_version.status != AgentVersionStatus.PUBLISHED:
        raise InvalidAgentVersionError("Agent version must be published.")


def _needs_signing_secret(channel: str) -> bool:
    return channel != ChannelType.WEB_CHAT


@transaction.atomic
def create_endpoint(
    *,
    workspace,
    actor,
    channel: str,
    name: str,
    agent_version: AgentVersion,
    integration_connection=None,
    unknown_customer_policy: str = UnknownCustomerPolicy.CREATE,
    configuration: dict | None = None,
    request_id: str | None = None,
) -> tuple[ChannelEndpoint, str | None]:
    """Returns ``(endpoint, plaintext_secret)``. ``plaintext_secret`` is
    ``None`` for a ``WEB_CHAT`` endpoint (section 17, 45: session-capability
    security, not a signature) and is otherwise returned exactly once, here
    (section 15)."""
    _validate_agent_version(workspace=workspace, agent_version=agent_version)

    plaintext_secret = None
    encrypted_secret = ""
    secret_created_at = None
    if _needs_signing_secret(channel):
        plaintext_secret = generate_signing_secret()
        encrypted_secret = encrypt_credentials({"secret": plaintext_secret})
        secret_created_at = timezone.now()

    endpoint = ChannelEndpoint.objects.create(
        workspace=workspace,
        channel=channel,
        name=name[:MAX_NAME_LENGTH],
        agent_version=agent_version,
        integration_connection=integration_connection,
        unknown_customer_policy=unknown_customer_policy,
        encrypted_signing_secret=encrypted_secret,
        secret_created_at=secret_created_at,
        configuration=configuration or {},
        created_by=actor,
    )
    record_event(
        action=AuditAction.CHANNEL_ENDPOINT_CREATED,
        target_type="channel_endpoint",
        target_id=endpoint.id,
        actor=actor,
        workspace=workspace,
        metadata={"channel": channel},
        request_id=request_id,
    )
    return endpoint, plaintext_secret


@transaction.atomic
def update_endpoint(
    *,
    workspace,
    endpoint: ChannelEndpoint,
    actor,
    name: str | None = None,
    agent_version: AgentVersion | None = None,
    unknown_customer_policy: str | None = None,
    configuration: dict | None = None,
    request_id: str | None = None,
) -> ChannelEndpoint:
    update_fields: list[str] = []
    if name is not None:
        endpoint.name = name[:MAX_NAME_LENGTH]
        update_fields.append("name")
    if agent_version is not None:
        _validate_agent_version(workspace=workspace, agent_version=agent_version)
        endpoint.agent_version = agent_version
        update_fields.append("agent_version")
    if unknown_customer_policy is not None:
        endpoint.unknown_customer_policy = unknown_customer_policy
        update_fields.append("unknown_customer_policy")
    if configuration is not None:
        endpoint.configuration = configuration
        update_fields.append("configuration")
    if not update_fields:
        return endpoint

    update_fields.append("updated_at")
    endpoint.save(update_fields=update_fields)
    record_event(
        action=AuditAction.CHANNEL_ENDPOINT_UPDATED,
        target_type="channel_endpoint",
        target_id=endpoint.id,
        actor=actor,
        workspace=workspace,
        metadata={},
        request_id=request_id,
    )
    return endpoint


@transaction.atomic
def set_endpoint_status(
    *, workspace, endpoint: ChannelEndpoint, actor, status: str, request_id: str | None = None
) -> ChannelEndpoint:
    if status not in ChannelEndpointStatus.values:
        raise ValueError(f"Invalid channel endpoint status: {status!r}")
    endpoint.status = status
    endpoint.save(update_fields=["status", "updated_at"])
    record_event(
        action=(
            AuditAction.CHANNEL_ENDPOINT_DISABLED
            if status == ChannelEndpointStatus.DISABLED
            else AuditAction.CHANNEL_ENDPOINT_ENABLED
        ),
        target_type="channel_endpoint",
        target_id=endpoint.id,
        actor=actor,
        workspace=workspace,
        metadata={"status": status},
        request_id=request_id,
    )
    return endpoint


@transaction.atomic
def rotate_secret(
    *, workspace, endpoint: ChannelEndpoint, actor, request_id: str | None = None
) -> tuple[ChannelEndpoint, str]:
    if not _needs_signing_secret(endpoint.channel):
        raise ValueError("This channel endpoint type does not use a signing secret.")
    plaintext_secret = generate_signing_secret()
    endpoint.encrypted_signing_secret = encrypt_credentials({"secret": plaintext_secret})
    endpoint.secret_created_at = timezone.now()
    endpoint.save(update_fields=["encrypted_signing_secret", "secret_created_at", "updated_at"])
    record_event(
        action=AuditAction.CHANNEL_SECRET_ROTATED,
        target_type="channel_endpoint",
        target_id=endpoint.id,
        actor=actor,
        workspace=workspace,
        metadata={},
        request_id=request_id,
    )
    return endpoint, plaintext_secret
