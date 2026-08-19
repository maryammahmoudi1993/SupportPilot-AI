"""Policy configuration serializers. Every authoritative field (status,
created_by, version numbers, activation state) is server-derived — client
input is accepted only through the narrow create/update serializers below
(section 79)."""

from __future__ import annotations

from rest_framework import serializers

from .models import (
    MAX_POLICY_DESCRIPTION_LENGTH,
    MAX_POLICY_NAME_LENGTH,
    MAX_RULE_NAME_LENGTH,
    Policy,
    PolicyEffect,
    PolicyRule,
    PolicyVersion,
)
from .predicates import known_predicate_names


class PolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = Policy
        fields = ["id", "name", "description", "status", "created_by", "created_at", "updated_at"]
        read_only_fields = fields


class PolicyCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=MAX_POLICY_NAME_LENGTH)
    description = serializers.CharField(
        max_length=MAX_POLICY_DESCRIPTION_LENGTH, required=False, allow_blank=True
    )


class PolicyUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=MAX_POLICY_NAME_LENGTH, required=False)
    description = serializers.CharField(
        max_length=MAX_POLICY_DESCRIPTION_LENGTH, required=False, allow_blank=True
    )


class PolicyRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = PolicyRule
        fields = [
            "id",
            "name",
            "priority",
            "enabled",
            "tool_key",
            "risk_levels",
            "side_effect_types",
            "condition_config",
            "effect",
            "required_role",
            "approval_ttl_seconds",
            "created_at",
        ]
        read_only_fields = fields


class PolicyVersionSerializer(serializers.ModelSerializer):
    rules = PolicyRuleSerializer(many=True, read_only=True)

    class Meta:
        model = PolicyVersion
        fields = ["id", "version", "status", "created_by", "created_at", "published_at", "rules"]
        read_only_fields = fields


MAX_CONDITION_ENTRIES = 10


class PolicyRuleCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=MAX_RULE_NAME_LENGTH)
    priority = serializers.IntegerField(min_value=0, max_value=100_000)
    enabled = serializers.BooleanField(required=False, default=True)
    tool_key = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")
    risk_levels = serializers.ListField(
        child=serializers.CharField(max_length=20), required=False, default=list
    )
    side_effect_types = serializers.ListField(
        child=serializers.CharField(max_length=20), required=False, default=list
    )
    condition_config = serializers.JSONField(required=False)
    effect = serializers.ChoiceField(choices=PolicyEffect.choices)
    required_role = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default=""
    )
    approval_ttl_seconds = serializers.IntegerField(
        min_value=60, max_value=60 * 60 * 24 * 30, required=False, allow_null=True
    )

    def validate_condition_config(self, value):
        if value is None:
            return {"all": []}
        if not isinstance(value, dict) or set(value) - {"all"}:
            raise serializers.ValidationError("condition_config must be an object with only 'all'.")
        entries = value.get("all", [])
        if not isinstance(entries, list) or len(entries) > MAX_CONDITION_ENTRIES:
            raise serializers.ValidationError(
                f"condition_config.all must be a list of at most {MAX_CONDITION_ENTRIES} entries."
            )
        known = known_predicate_names()
        for entry in entries:
            if not isinstance(entry, dict) or "predicate" not in entry:
                raise serializers.ValidationError("Each entry must include a 'predicate' name.")
            if entry["predicate"] not in known:
                raise serializers.ValidationError(f"Unknown predicate: {entry['predicate']!r}.")
        return value
