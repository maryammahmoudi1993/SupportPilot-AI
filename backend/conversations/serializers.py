"""Conversation and message serializers.

Serializers validate request shape only; ``workspace``, sender identity, and
activity timestamps are always derived server-side (see
``conversations.services``) and are never client-writable.
"""

from __future__ import annotations

from rest_framework import serializers

from workspaces.models import WorkspaceMembership

from .models import (
    Conversation,
    ConversationChannel,
    ConversationStatus,
    Message,
    MessageDirection,
)


class MembershipSummarySerializer(serializers.ModelSerializer):
    """Minimal, safe assignee representation."""

    email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = WorkspaceMembership
        fields = ["id", "email", "role"]
        read_only_fields = fields


class ConversationSerializer(serializers.ModelSerializer):
    assigned_to = MembershipSummarySerializer(read_only=True)
    customer_id = serializers.UUIDField(source="customer.id", read_only=True)

    class Meta:
        model = Conversation
        fields = [
            "id",
            "customer_id",
            "channel",
            "status",
            "subject",
            "assigned_to",
            "external_id",
            "started_at",
            "last_message_at",
            "closed_at",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ConversationCreateSerializer(serializers.Serializer):
    customer_id = serializers.UUIDField()
    channel = serializers.ChoiceField(
        choices=ConversationChannel.choices, default=ConversationChannel.WEB
    )
    subject = serializers.CharField(max_length=300, required=False, allow_blank=True)
    external_id = serializers.CharField(max_length=255, required=False, allow_null=True)
    metadata = serializers.JSONField(required=False)


class ConversationAssignSerializer(serializers.Serializer):
    membership_id = serializers.UUIDField(required=False)


class ConversationStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=ConversationStatus.choices)


class MessageSerializer(serializers.ModelSerializer):
    sender = MembershipSummarySerializer(source="sender_membership", read_only=True)

    class Meta:
        model = Message
        fields = [
            "id",
            "sender_type",
            "sender",
            "direction",
            "body",
            "external_id",
            "metadata",
            "created_at",
        ]
        read_only_fields = fields


class MessageCreateSerializer(serializers.Serializer):
    """Deliberately restricted: the client cannot claim ``sender_type`` —
    every message created through this API is authored by the authenticated
    staff member and may only be ``outbound`` (to the customer) or
    ``internal`` (support-only note)."""

    direction = serializers.ChoiceField(
        choices=[MessageDirection.OUTBOUND.value, MessageDirection.INTERNAL.value]
    )
    body = serializers.CharField(allow_blank=False)
    external_id = serializers.CharField(max_length=255, required=False, allow_null=True)
    metadata = serializers.JSONField(required=False)
