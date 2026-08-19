"""Integrations app config."""

from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations"
    verbose_name = "Integrations"

    def ready(self) -> None:
        # Pure in-memory registration, mirroring tools/apps.py (section 9):
        # the code-owned registry is always the source of truth, synced to
        # the database mirror separately (see the seed migration).
        from tools.registry import registry

        from .tools import register_integration_tools

        register_integration_tools(registry)
