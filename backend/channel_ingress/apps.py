"""Channel-ingress app config."""

from django.apps import AppConfig


class ChannelIngressConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "channel_ingress"
    verbose_name = "Multi-channel ingress"

    def ready(self) -> None:
        # Pure in-memory registration, mirroring
        # ``notifications.apps.NotificationsConfig.ready`` (Phase 10 Block 2):
        # the channel-response delivery handler is wired up here so the
        # generic ``notifications`` delivery engine can resolve it without
        # importing ``channel_ingress`` at module load time.
        from notifications.handlers import register_channel_handler
        from notifications.models import DeliveryChannel

        from .response_delivery import handle_channel_response_delivery_attempt

        register_channel_handler(
            DeliveryChannel.CHANNEL_RESPONSE, handle_channel_response_delivery_attempt
        )
