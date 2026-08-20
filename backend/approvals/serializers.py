"""Approval serializers. Every authoritative field (status, required_role,
requested_by, safe_context) is server-derived — the only client-suppliable
input anywhere in this module is an optional decision comment (section 79,
82, 116-117)."""

from __future__ import annotations

from rest_framework import serializers

from .models import MAX_COMMENT_LENGTH, ApprovalDecision, ApprovalRequest


class ApprovalDecisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApprovalDecision
        fields = ["id", "decision", "decided_by", "safe_comment", "created_at"]
        read_only_fields = fields


class ApprovalRequestSerializer(serializers.ModelSerializer):
    decision = ApprovalDecisionSerializer(read_only=True)

    class Meta:
        model = ApprovalRequest
        fields = [
            "id",
            "status",
            "required_role",
            "requested_by",
            "summary",
            "safe_context",
            "expires_at",
            "created_at",
            "resolved_at",
            "decision",
        ]
        read_only_fields = fields


class ApprovalDecisionInputSerializer(serializers.Serializer):
    """The only body an approve/reject call accepts. Notably absent:
    ``decision`` (the endpoint URL is the decision), ``approved_by``/
    ``decided_by`` (always the authenticated caller), ``required_role``
    (server-derived at request-creation time, never client-suppliable)."""

    comment = serializers.CharField(
        max_length=MAX_COMMENT_LENGTH, required=False, allow_blank=True, default=""
    )
