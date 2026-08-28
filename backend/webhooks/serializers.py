"""Explicit, secret-free API contracts (section 12, 37-38, 43).

``WebhookEndpointSerializer`` never includes ``encrypted_signing_secret`` or
any plaintext — the raw signing secret is only ever returned by the
dedicated create/rotate response serializers below, and only once, at the
moment it is generated.
"""

from __future__ import annotations

from rest_framework import serializers

from .models import WebhookDelivery, WebhookEndpoint, WebhookEndpointStatus, WebhookEventType

MAX_NAME_LENGTH = 200
MAX_URL_LENGTH = 2048


class WebhookEndpointSerializer(serializers.ModelSerializer):
    secret_configured = serializers.BooleanField(read_only=True)

    class Meta:
        model = WebhookEndpoint
        fields = [
            "id",
            "name",
            "url",
            "status",
            "subscribed_event_types",
            "secret_configured",
            "secret_created_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class WebhookEndpointCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=MAX_NAME_LENGTH)
    url = serializers.CharField(max_length=MAX_URL_LENGTH)
    subscribed_event_types = serializers.ListField(
        child=serializers.ChoiceField(choices=WebhookEventType.choices), allow_empty=False
    )


class WebhookEndpointCreateResponseSerializer(serializers.Serializer):
    """Documents the create response shape for schema generation only
    (section 37) — a plain ``Serializer``, not bound to the
    ``WebhookEndpoint`` model, because the raw secret it includes is never
    a model attribute. The view builds this response by merging
    ``WebhookEndpointSerializer(endpoint).data`` with the plaintext secret,
    returned exactly once (section 13)."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    url = serializers.CharField()
    status = serializers.CharField()
    subscribed_event_types = serializers.ListField(child=serializers.CharField())
    secret_configured = serializers.BooleanField()
    secret_created_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    signing_secret = serializers.CharField()


class WebhookEndpointUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=MAX_NAME_LENGTH, required=False)
    url = serializers.CharField(max_length=MAX_URL_LENGTH, required=False)
    subscribed_event_types = serializers.ListField(
        child=serializers.ChoiceField(choices=WebhookEventType.choices),
        allow_empty=False,
        required=False,
    )


class WebhookEndpointStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=WebhookEndpointStatus.choices)


class WebhookRotateSecretResponseSerializer(serializers.Serializer):
    signing_secret = serializers.CharField()


class WebhookDeliverySerializer(serializers.Serializer):
    """Safe operational inspection fields only (section 43) — never the
    signing secret, raw request headers, signature, or full event payload."""

    delivery_id = serializers.UUIDField()
    event_id = serializers.UUIDField()
    event_type = serializers.CharField(source="event.event_type")
    endpoint_id = serializers.UUIDField()
    endpoint_name = serializers.CharField(source="endpoint.name")
    status = serializers.CharField(source="delivery.status")
    attempt_count = serializers.IntegerField(source="delivery.attempt_count")
    max_attempts = serializers.IntegerField(source="delivery.max_attempts")
    next_attempt_at = serializers.DateTimeField(source="delivery.next_attempt_at")
    last_error_code = serializers.CharField(source="delivery.last_error_code")
    last_http_status = serializers.SerializerMethodField()
    delivered_at = serializers.DateTimeField(source="delivery.delivered_at")
    failed_at = serializers.DateTimeField(source="delivery.failed_at")
    created_at = serializers.DateTimeField()

    def get_last_http_status(self, obj: WebhookDelivery) -> int | None:
        latest = obj.delivery.attempts.order_by("-attempt_number").first()
        return latest.response_status_code if latest else None
