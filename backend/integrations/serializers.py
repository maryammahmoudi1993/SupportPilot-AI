"""Explicit, secret-free API contracts (section 17, 64-67).

``IntegrationConnectionSerializer`` never includes ``encrypted_credentials``
or any plaintext — only safe status metadata. Credential input is
write-only and only ever accepted through the dedicated create/rotate
serializers below, never through ordinary mass-assignable model fields.
"""

from __future__ import annotations

from rest_framework import serializers

from .models import IntegrationConnection, IntegrationEnvironment, IntegrationProvider

MAX_CREDENTIALS_BYTES = 8000
MAX_CONFIGURATION_BYTES = 8000


def _validate_json_size(value: dict, *, max_bytes: int) -> None:
    import json

    if len(json.dumps(value)) > max_bytes:
        raise serializers.ValidationError("Payload is too large.")


class IntegrationConnectionSerializer(serializers.ModelSerializer):
    credentials_configured = serializers.BooleanField(read_only=True)
    capabilities = serializers.SerializerMethodField()

    class Meta:
        model = IntegrationConnection
        fields = [
            "id",
            "provider",
            "display_name",
            "status",
            "environment",
            "configuration",
            "credentials_configured",
            "credential_version",
            "capabilities",
            "last_checked_at",
            "last_success_at",
            "last_error_code",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_capabilities(self, obj: IntegrationConnection) -> list[str]:
        return sorted(obj.capabilities)


class IntegrationConnectionCreateSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=IntegrationProvider.choices)
    display_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    environment = serializers.ChoiceField(
        choices=IntegrationEnvironment.choices, default=IntegrationEnvironment.TEST
    )
    credentials = serializers.JSONField(
        write_only=True,
        validators=[lambda v: _validate_json_size(v, max_bytes=MAX_CREDENTIALS_BYTES)],
    )
    configuration = serializers.JSONField(
        required=False,
        default=dict,
        validators=[lambda v: _validate_json_size(v, max_bytes=MAX_CONFIGURATION_BYTES)],
    )


class IntegrationConnectionUpdateSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    configuration = serializers.JSONField(
        required=False,
        validators=[lambda v: _validate_json_size(v, max_bytes=MAX_CONFIGURATION_BYTES)],
    )


class IntegrationCredentialRotateSerializer(serializers.Serializer):
    credentials = serializers.JSONField(
        write_only=True,
        validators=[lambda v: _validate_json_size(v, max_bytes=MAX_CREDENTIALS_BYTES)],
    )


class IntegrationConnectionEnabledSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()


class IntegrationConnectionTestResultSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    status = serializers.CharField()
    error_code = serializers.CharField(allow_null=True)
