"""Explicit API contracts. Server-derived fields (workspace, run counters,
status, scorer output, usage) are never client-writable."""

from __future__ import annotations

from rest_framework import serializers

from .models import (
    EvaluationCase,
    EvaluationCaseStatus,
    EvaluationDataset,
    EvaluationDatasetStatus,
    EvaluationResult,
    EvaluationRun,
)

MAX_NAME_CHARS = 200
MAX_INPUT_MESSAGE_CHARS = 8000


class EvaluationDatasetSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvaluationDataset
        fields = ["id", "name", "description", "status", "created_at", "updated_at"]
        read_only_fields = fields


class EvaluationDatasetWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=MAX_NAME_CHARS)
    description = serializers.CharField(required=False, allow_blank=True)
    status = serializers.ChoiceField(choices=EvaluationDatasetStatus.choices, required=False)


class EvaluationCaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvaluationCase
        fields = [
            "id",
            "key",
            "name",
            "status",
            "input_message",
            "seeded_context",
            "expectations",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class EvaluationCaseWriteSerializer(serializers.Serializer):
    key = serializers.SlugField(max_length=128)
    name = serializers.CharField(max_length=MAX_NAME_CHARS)
    status = serializers.ChoiceField(choices=EvaluationCaseStatus.choices, required=False)
    input_message = serializers.CharField(max_length=MAX_INPUT_MESSAGE_CHARS)
    seeded_context = serializers.JSONField(required=False)
    expectations = serializers.JSONField(required=False)


class EvaluationRunSerializer(serializers.ModelSerializer):
    dataset_id = serializers.UUIDField(read_only=True)
    agent_version_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = EvaluationRun
        fields = [
            "id",
            "dataset_id",
            "agent_version_id",
            "status",
            "provider_mode",
            "threshold_config",
            "total_cases",
            "completed_cases",
            "passed_cases",
            "failed_cases",
            "started_at",
            "completed_at",
            "cancelled_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class EvaluationRunCreateSerializer(serializers.Serializer):
    dataset_id = serializers.UUIDField()
    agent_version_id = serializers.UUIDField()
    threshold_config = serializers.JSONField(required=False)


class EvaluationResultSerializer(serializers.ModelSerializer):
    case_key = serializers.CharField(source="case_snapshot.case_key", read_only=True)
    agent_run_id = serializers.UUIDField(read_only=True)
    replay_of_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = EvaluationResult
        fields = [
            "id",
            "case_key",
            "status",
            "agent_run_id",
            "scorer_output",
            "passed",
            "failure_code",
            "failure_message_safe",
            "latency_ms",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "estimated_cost_usd",
            "replay_of_id",
            "started_at",
            "completed_at",
            "created_at",
        ]
        read_only_fields = fields


class EvaluationRunCompareSerializer(serializers.Serializer):
    baseline_run_id = serializers.UUIDField()
    candidate_run_id = serializers.UUIDField()
