"""Channel adapter registry — resolves a ``ChannelType`` to its
``ChannelAdapter`` implementation. Web chat is deliberately absent: it uses
its own bounded session-capability security model (section 41, 45), never
this signature-based adapter path."""

from __future__ import annotations

from ..errors import UnsupportedEventError
from ..models import ChannelType
from .base import ChannelAdapter
from .email_adapter import EmailInboundAdapter
from .generic_webhook import GenericSignedWebhookAdapter

_ADAPTERS: dict[str, ChannelAdapter] = {}
_ADAPTERS[str(ChannelType.GENERIC_WEBHOOK)] = GenericSignedWebhookAdapter()
_ADAPTERS[str(ChannelType.EMAIL)] = EmailInboundAdapter()


def get_adapter(channel: str) -> ChannelAdapter:
    adapter = _ADAPTERS.get(channel)
    if adapter is None:
        raise UnsupportedEventError()
    return adapter


__all__ = ["ChannelAdapter", "get_adapter"]
