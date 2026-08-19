"""Explicit API contracts. Server-derived fields (workspace, counters, status,
usage, cost) are never client-writable."""

from __future__ import annotations

from rest_framework import serializers

from .models import (
    AgentDefinition,
    AgentDefinitionStatus,
    AgentProvider,
    AgentRun,
    AgentRunTrigger,
    AgentStep,
    AgentVersion,
)
from .services import MAX_INPUT_MESSAGE_CHARS

MAX_SYSTEM_PROMPT_CHARS = 8000
MAX_NAME_CHARS = 200
MAX_METADATA_BYTES = 8000


def _validate_metadata_size(value: dict) -> None:
    import json

    if len(json.dumps(value)) > MAX_METADATA_BYTES:
        raise serializers.ValidationError("Metadata payload is too large.")


class AgentDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentDefinition
        fields = ["id", "name", "description", "status", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class AgentDefinitionWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=MAX_NAME_CHARS)
    description = serializers.CharField(required=False, allow_blank=True)
    status = serializers.ChoiceField(choices=AgentDefinitionStatus.choices, required=False)


class AgentVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentVersion
        fields = [
            "id",
            "version",
            "status",
            "provider",
            "model",
            "system_prompt",
            "temperature",
            "max_output_tokens",
            "max_model_calls",
            "max_steps",
            "wall_time_limit_seconds",
            "provider_timeout_seconds",
            "max_total_tokens",
            "max_estimated_cost_usd",
            "max_retry_attempts",
            "max_tool_calls",
            "runtime_config",
            "published_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class AgentVersionWriteSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=AgentProvider.choices)
    model = serializers.CharField(max_length=128)
    system_prompt = serializers.CharField(
        required=False, allow_blank=True, max_length=MAX_SYSTEM_PROMPT_CHARS
    )
    temperature = serializers.FloatField(required=False, min_value=0.0, max_value=2.0)
    max_output_tokens = serializers.IntegerField(required=False, min_value=1, max_value=32000)
    max_model_calls = serializers.IntegerField(required=False, min_value=1, max_value=50)
    max_steps = serializers.IntegerField(required=False, min_value=1, max_value=200)
    wall_time_limit_seconds = serializers.IntegerField(required=False, min_value=1, max_value=600)
    provider_timeout_seconds = serializers.IntegerField(required=False, min_value=1, max_value=300)
    max_total_tokens = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, max_value=2_000_000
    )
    max_estimated_cost_usd = serializers.DecimalField(
        required=False, allow_null=True, max_digits=10, decimal_places=4, min_value=0
    )
    max_retry_attempts = serializers.IntegerField(required=False, min_value=1, max_value=5)
    max_tool_calls = serializers.IntegerField(required=False, min_value=0, max_value=20)
    runtime_config = serializers.JSONField(required=False, validators=[_validate_metadata_size])


class AgentRunSerializer(serializers.ModelSerializer):
    agent_version_id = serializers.UUIDField(read_only=True)
    agent_definition_id = serializers.UUIDField(
        source="agent_version.agent_definition_id", read_only=True
    )

    class Meta:
        model = AgentRun
        fields = [
            "id",
            "agent_version_id",
            "agent_definition_id",
            "conversation_id",
            "ticket_id",
            "trigger",
            "status",
            "input_message",
            "input_metadata",
            "final_response",
            "started_at",
            "completed_at",
            "cancelled_at",
            "failure_code",
            "failure_message_safe",
            "model_call_count",
            "step_count",
            "tool_call_count",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "estimated_cost_usd",
            "correlation_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class AgentRunCreateSerializer(serializers.Serializer):
    agent_version_id = serializers.UUIDField()
    input_message = serializers.CharField(max_length=MAX_INPUT_MESSAGE_CHARS)
    trigger = serializers.ChoiceField(choices=AgentRunTrigger.choices, required=False)
    conversation_id = serializers.UUIDField(required=False, allow_null=True)
    ticket_id = serializers.UUIDField(required=False, allow_null=True)
    input_metadata = serializers.JSONField(required=False, validators=[_validate_metadata_size])


class AgentStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentStep
        fields = [
            "id",
            "sequence",
            "step_type",
            "status",
            "provider",
            "model",
            "input_summary",
            "output_summary",
            "safe_metadata",
            "started_at",
            "completed_at",
            "latency_ms",
            "error_code",
            "created_at",
        ]
        read_only_fields = fields
