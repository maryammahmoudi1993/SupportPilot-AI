# Generated for Phase 6: seeds the safe demo tool catalog.
#
# Mirrors the code-owned ``tools.demo_tools`` registrations into
# ``ToolDefinition`` rows. Deliberately hardcoded here (not imported from
# app code) so this migration keeps producing the same historical result
# even if the demo tools module changes later — migrations run against a
# point-in-time schema, not live application code (section 13-14).
from __future__ import annotations

from django.db import migrations

DEMO_TOOLS = [
    {
        "key": "demo.echo",
        "display_name": "Echo",
        "description": "Deterministically echoes back the provided message. Read-only, no side effects.",
        "handler_key": "demo.echo",
        "risk_level": "read_only",
        "side_effect_type": "none",
        "default_timeout_seconds": 5,
        "max_timeout_seconds": 10,
        "max_retries": 0,
        "idempotency_mode": "safe",
    },
    {
        "key": "demo.add",
        "display_name": "Add",
        "description": "Deterministically adds two integers. Read-only, no side effects.",
        "handler_key": "demo.add",
        "risk_level": "read_only",
        "side_effect_type": "none",
        "default_timeout_seconds": 5,
        "max_timeout_seconds": 10,
        "max_retries": 0,
        "idempotency_mode": "safe",
    },
    {
        "key": "demo.flaky",
        "display_name": "Flaky (test) tool",
        "description": (
            "Deterministically fails a configured number of times before succeeding; can sleep "
            "to prove timeout enforcement. For platform verification only."
        ),
        "handler_key": "demo.flaky",
        "risk_level": "read_only",
        "side_effect_type": "none",
        "default_timeout_seconds": 1,
        "max_timeout_seconds": 2,
        "max_retries": 3,
        "idempotency_mode": "safe",
    },
]


def seed_demo_tools(apps, schema_editor):
    ToolDefinition = apps.get_model("tools", "ToolDefinition")
    for data in DEMO_TOOLS:
        ToolDefinition.objects.update_or_create(key=data["key"], defaults=data)


def remove_demo_tools(apps, schema_editor):
    ToolDefinition = apps.get_model("tools", "ToolDefinition")
    ToolDefinition.objects.filter(key__in=[t["key"] for t in DEMO_TOOLS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("tools", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_demo_tools, remove_demo_tools),
    ]
