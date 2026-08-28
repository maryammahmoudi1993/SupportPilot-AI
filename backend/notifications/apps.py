"""Notifications app config."""

from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"
    verbose_name = "Notifications"

    def ready(self) -> None:
        # Pure in-memory registration, mirroring
        # ``integrations.apps.IntegrationsConfig.ready`` (Phase 10 Block 2
        # section 4): the notification channel handler is wired up here so
        # ``process_claimed_delivery`` can resolve it without importing
        # ``integrations`` at module load time.
        from .handlers import register_channel_handler
        from .models import DeliveryChannel
        from .notification_delivery import handle_notification_delivery_attempt

        register_channel_handler(DeliveryChannel.NOTIFICATION, handle_notification_delivery_attempt)
