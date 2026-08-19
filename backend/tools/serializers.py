"""Explicit API contracts. Only safe catalog metadata is ever serialized —
never a handler class path, internal module, or secret configuration
(section 60). Server-derived fields (workspace, status, timing, results) are
never client-writable."""

from __future__ import annotations

from rest_framework import serializers

from .models import ToolBinding, ToolDefinition, ToolExecution

MAX_CONFIGURATION_BYTES = 2000


def _validate_configuration_size(value: dict) -> None:
    import json

    if len(json.dumps(value)) > MAX_CONFIGURATION_BYTES:
        raise serializers.ValidationError("Configuration payload is too large.")


class ToolDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ToolDefinition
        fields = [
            "id",
            "key",
            "display_name",
            "description",
            "status",
            "risk_level",
            "side_effect_type",
            "default_timeout_seconds",
            "max_timeout_seconds",
            "max_retries",
            "idempotency_mode",
        ]
        read_only_fields = fields


class ToolBindingSerializer(serializers.ModelSerializer):
    tool_key = serializers.CharField(source="tool_definition.key", read_only=True)
    tool_display_name = serializers.CharField(source="tool_definition.display_name", read_only=True)

    class Meta:
        model = ToolBinding
        fields = [
            "id",
            "tool_definition_id",
            "tool_key",
            "tool_display_name",
            "enabled",
            "configuration",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ToolBindingCreateSerializer(serializers.Serializer):
    tool_key = serializers.CharField(max_length=128)
    configuration = serializers.JSONField(required=False, validators=[_validate_configuration_size])


class ToolBindingUpdateSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()


class ToolExecutionSerializer(serializers.ModelSerializer):
    tool_key = serializers.CharField(source="tool_definition.key", read_only=True)

    class Meta:
        model = ToolExecution
        fields = [
            "id",
            "agent_run_id",
            "tool_definition_id",
            "tool_key",
            "status",
            "idempotency_key",
            "arguments_redacted",
            "result_redacted",
            "attempt_count",
            "timeout_seconds",
            "started_at",
            "completed_at",
            "error_code",
            "error_message_safe",
            "duration_ms",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
