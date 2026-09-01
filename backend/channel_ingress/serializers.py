"""Explicit, secret-free API contracts (mirrors ``webhooks.serializers``).

``ChannelEndpointSerializer`` never includes ``encrypted_signing_secret`` or
any plaintext — the raw secret is only ever returned by the dedicated
create/rotate response serializers, and only once.
"""

from __future__ import annotations

from rest_framework import serializers

from .models import ChannelEndpoint, ChannelEndpointStatus, ChannelType, UnknownCustomerPolicy

MAX_NAME_LENGTH = 200
MAX_CHAT_MESSAGE_LENGTH = 8000


class ChannelEndpointSerializer(serializers.ModelSerializer):
    secret_configured = serializers.BooleanField(read_only=True)

    class Meta:
        model = ChannelEndpoint
        fields = [
            "id",
            "channel",
            "name",
            "status",
            "agent_version",
            "integration_connection",
            "unknown_customer_policy",
            "configuration",
            "secret_configured",
            "secret_created_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ChannelEndpointCreateSerializer(serializers.Serializer):
    channel = serializers.ChoiceField(choices=ChannelType.choices)
    name = serializers.CharField(max_length=MAX_NAME_LENGTH)
    agent_version_id = serializers.UUIDField()
    integration_connection_id = serializers.UUIDField(required=False, allow_null=True)
    unknown_customer_policy = serializers.ChoiceField(
        choices=UnknownCustomerPolicy.choices, required=False, default=UnknownCustomerPolicy.CREATE
    )
    configuration = serializers.JSONField(required=False, default=dict)


class ChannelEndpointCreateResponseSerializer(serializers.Serializer):
    """Schema-generation-only response shape (never bound to the model,
    since the raw secret is never a model attribute) — the view builds it by
    merging ``ChannelEndpointSerializer(endpoint).data`` with the plaintext
    secret when one was generated."""

    id = serializers.UUIDField()
    channel = serializers.CharField()
    name = serializers.CharField()
    status = serializers.CharField()
    agent_version = serializers.UUIDField()
    integration_connection = serializers.UUIDField(allow_null=True)
    unknown_customer_policy = serializers.CharField()
    configuration = serializers.JSONField()
    secret_configured = serializers.BooleanField()
    secret_created_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    signing_secret = serializers.CharField(allow_null=True)


class ChannelEndpointUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=MAX_NAME_LENGTH, required=False)
    agent_version_id = serializers.UUIDField(required=False)
    unknown_customer_policy = serializers.ChoiceField(
        choices=UnknownCustomerPolicy.choices, required=False
    )
    configuration = serializers.JSONField(required=False)


class ChannelEndpointStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=ChannelEndpointStatus.choices)


class ChannelRotateSecretResponseSerializer(serializers.Serializer):
    signing_secret = serializers.CharField()


class InboundChannelEventSerializer(serializers.Serializer):
    """Safe operational inspection fields only — never the raw provider
    payload, headers, or signature."""

    id = serializers.UUIDField()
    endpoint_id = serializers.UUIDField(source="endpoint.id")
    channel = serializers.CharField(source="endpoint.channel")
    status = serializers.CharField()
    failure_code = serializers.CharField()
    conversation_id = serializers.UUIDField(allow_null=True)
    message_id = serializers.UUIDField(allow_null=True)
    received_at = serializers.DateTimeField()
    processed_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()


# ---------------------------------------------------------------------------
# Public web-chat contracts (section 16-18, 41) — deliberately separate from
# the staff-facing serializers above: different trust boundary, different
# allowed fields.
# ---------------------------------------------------------------------------


class ChatSessionBootstrapResponseSerializer(serializers.Serializer):
    session_token = serializers.CharField()
    expires_at = serializers.DateTimeField()


class ChatMessageSubmitSerializer(serializers.Serializer):
    client_message_id = serializers.CharField(max_length=255)
    body = serializers.CharField(max_length=MAX_CHAT_MESSAGE_LENGTH, allow_blank=False)


class ChatMessageSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    sender_type = serializers.CharField()
    body = serializers.CharField()
    created_at = serializers.DateTimeField()


class ChatMessageSubmitResponseSerializer(serializers.Serializer):
    accepted = serializers.BooleanField()
    message_id = serializers.UUIDField()
