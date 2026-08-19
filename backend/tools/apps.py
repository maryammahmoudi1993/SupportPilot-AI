"""Tools app config."""

from django.apps import AppConfig


class ToolsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tools"
    verbose_name = "Tools"

    def ready(self) -> None:
        # Pure in-memory registration — no DB access at import time. The
        # database mirror (``ToolDefinition``) is synced separately via a
        # migration/fixture, never here (section 15).
        from .demo_tools import register_demo_tools
        from .registry import registry

        register_demo_tools(registry)
