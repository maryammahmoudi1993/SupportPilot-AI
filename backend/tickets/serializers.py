"""Ticket serializers.

Serializers validate request shape only; ``workspace``, ``resolved_at``, and
assignment are always derived server-side (see ``tickets.services``).
"""

from __future__ import annotations

from rest_framework import serializers

from conversations.serializers import MembershipSummarySerializer

from .models import Ticket, TicketPriority, TicketStatus


class TicketSerializer(serializers.ModelSerializer):
    assigned_to = MembershipSummarySerializer(read_only=True)
    customer_id = serializers.UUIDField(source="customer.id", read_only=True)
    conversation_id = serializers.UUIDField(
        source="conversation.id", read_only=True, allow_null=True
    )

    class Meta:
        model = Ticket
        fields = [
            "id",
            "customer_id",
            "conversation_id",
            "subject",
            "description",
            "status",
            "priority",
            "assigned_to",
            "due_at",
            "resolved_at",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class TicketCreateSerializer(serializers.Serializer):
    customer_id = serializers.UUIDField()
    conversation_id = serializers.UUIDField(required=False, allow_null=True)
    subject = serializers.CharField(max_length=300)
    description = serializers.CharField(required=False, allow_blank=True)
    priority = serializers.ChoiceField(
        choices=TicketPriority.choices, default=TicketPriority.NORMAL
    )
    due_at = serializers.DateTimeField(required=False, allow_null=True)
    metadata = serializers.JSONField(required=False)


class TicketUpdateSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=300, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    priority = serializers.ChoiceField(choices=TicketPriority.choices, required=False)
    due_at = serializers.DateTimeField(required=False, allow_null=True)
    metadata = serializers.JSONField(required=False)


class TicketAssignSerializer(serializers.Serializer):
    membership_id = serializers.UUIDField(required=False)


class TicketStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=TicketStatus.choices)
