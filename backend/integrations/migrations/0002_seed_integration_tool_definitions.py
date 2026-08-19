# Seeds the Phase 7 business tool catalog into ToolDefinition, mirroring
# tools/migrations/0002_seed_demo_tool_definitions.py. Hardcoded here (not
# imported from integrations.tools) so this migration keeps producing the
# same historical result even if application code changes later — migrations
# run against a point-in-time schema, not live application code.
from __future__ import annotations

from django.db import migrations

INTEGRATION_TOOLS = [
    {
        "key": "customer.lookup",
        "display_name": "Customer lookup",
        "description": "Look up a workspace customer by ID, email, or external reference.",
        "handler_key": "customer.lookup",
        "risk_level": "read_only",
        "side_effect_type": "read",
        "default_timeout_seconds": 5,
        "max_timeout_seconds": 10,
        "max_retries": 0,
        "idempotency_mode": "safe",
    },
    {
        "key": "order.lookup",
        "display_name": "Order lookup",
        "description": "Look up an order's status, amount, and shipment summary.",
        "handler_key": "order.lookup",
        "risk_level": "read_only",
        "side_effect_type": "read",
        "default_timeout_seconds": 8,
        "max_timeout_seconds": 15,
        "max_retries": 2,
        "idempotency_mode": "safe",
    },
    {
        "key": "shipment.lookup",
        "display_name": "Shipment lookup",
        "description": "Look up a shipment's tracking status and carrier.",
        "handler_key": "shipment.lookup",
        "risk_level": "read_only",
        "side_effect_type": "read",
        "default_timeout_seconds": 8,
        "max_timeout_seconds": 15,
        "max_retries": 2,
        "idempotency_mode": "safe",
    },
    {
        "key": "payment.lookup",
        "display_name": "Payment lookup",
        "description": "Look up a payment's status and refunded amount.",
        "handler_key": "payment.lookup",
        "risk_level": "read_only",
        "side_effect_type": "read",
        "default_timeout_seconds": 8,
        "max_timeout_seconds": 15,
        "max_retries": 2,
        "idempotency_mode": "safe",
    },
    {
        "key": "payment.refund",
        "display_name": "Payment refund",
        "description": (
            "Execute a sandbox refund against a payment. Phase 7 proves execution "
            "mechanics only; deterministic authorization policy and human approval "
            "gates are added in Phase 8."
        ),
        "handler_key": "payment.refund",
        "risk_level": "critical",
        "side_effect_type": "financial",
        "default_timeout_seconds": 10,
        "max_timeout_seconds": 15,
        "max_retries": 2,
        "idempotency_mode": "required",
    },
    {
        "key": "calendar.check_availability",
        "display_name": "Calendar availability",
        "description": "Check free/busy availability for a bounded time window.",
        "handler_key": "calendar.check_availability",
        "risk_level": "read_only",
        "side_effect_type": "read",
        "default_timeout_seconds": 8,
        "max_timeout_seconds": 15,
        "max_retries": 2,
        "idempotency_mode": "safe",
    },
    {
        "key": "calendar.create_booking",
        "display_name": "Calendar booking",
        "description": "Create a calendar booking for a workspace customer.",
        "handler_key": "calendar.create_booking",
        "risk_level": "high",
        "side_effect_type": "external_write",
        "default_timeout_seconds": 10,
        "max_timeout_seconds": 15,
        "max_retries": 2,
        "idempotency_mode": "required",
    },
    {
        "key": "ticket.create",
        "display_name": "Create ticket",
        "description": "Create a support ticket for a workspace customer.",
        "handler_key": "ticket.create",
        "risk_level": "medium",
        "side_effect_type": "internal_write",
        "default_timeout_seconds": 5,
        "max_timeout_seconds": 10,
        "max_retries": 0,
        "idempotency_mode": "required",
    },
    {
        "key": "ticket.update",
        "display_name": "Update ticket",
        "description": "Update a support ticket's status, priority, or add a note.",
        "handler_key": "ticket.update",
        "risk_level": "medium",
        "side_effect_type": "internal_write",
        "default_timeout_seconds": 5,
        "max_timeout_seconds": 10,
        "max_retries": 0,
        "idempotency_mode": "required",
    },
    {
        "key": "notification.send",
        "display_name": "Send customer notification",
        "description": "Send an email notification to a workspace customer.",
        "handler_key": "notification.send",
        "risk_level": "medium",
        "side_effect_type": "external_write",
        "default_timeout_seconds": 8,
        "max_timeout_seconds": 15,
        "max_retries": 2,
        "idempotency_mode": "required",
    },
]


def seed_integration_tools(apps, schema_editor):
    ToolDefinition = apps.get_model("tools", "ToolDefinition")
    for data in INTEGRATION_TOOLS:
        ToolDefinition.objects.update_or_create(key=data["key"], defaults=data)


def remove_integration_tools(apps, schema_editor):
    ToolDefinition = apps.get_model("tools", "ToolDefinition")
    ToolDefinition.objects.filter(key__in=[t["key"] for t in INTEGRATION_TOOLS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0001_initial"),
        ("tools", "0002_seed_demo_tool_definitions"),
    ]

    operations = [
        migrations.RunPython(seed_integration_tools, remove_integration_tools),
    ]
