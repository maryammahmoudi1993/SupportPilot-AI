"""Webhooks app config."""

from django.apps import AppConfig


class WebhooksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "webhooks"
    verbose_name = "Webhooks"

    def ready(self) -> None:
        # Pure in-memory registration (Phase 10 Block 3, section 33),
        # mirroring ``notifications.apps.NotificationsConfig.ready``: the
        # webhook channel handler is wired into Block 2's shared
        # per-channel registry here, not into the Celery task itself.
        from notifications.handlers import register_channel_handler
        from notifications.models import DeliveryChannel

        from .services import handle_webhook_delivery_attempt

        register_channel_handler(DeliveryChannel.WEBHOOK, handle_webhook_delivery_attempt)
