"""Per-channel delivery handler registry (Phase 10 Block 2).

Replaces the Block 1 placeholder that dead-lettered every claimed delivery
with ``delivery_handler_not_implemented`` — that was only ever acceptable
before a real producer existed (Block 1 section 21). Now that
``notification.send`` creates and enqueues real deliveries, an unregistered
channel must be detected *before* a claim (and therefore an attempt slot) is
consumed, not silently turned into a fake provider failure — see
``notifications.services.process_claimed_delivery``.

Purely in-memory registration, mirroring ``tools.registry`` /
``integrations.apps.IntegrationsConfig.ready`` — each channel's ``AppConfig``
registers its own handler at startup (``notifications/apps.py`` registers
``notification``; Block 3 registers ``webhook``).
"""

from __future__ import annotations

import uuid
from typing import Protocol

from .models import Delivery


class DeliveryHandler(Protocol):
    def __call__(self, *, delivery: Delivery, claim_token: uuid.UUID) -> None: ...


_HANDLERS: dict[str, DeliveryHandler] = {}


def register_channel_handler(channel: str, handler: DeliveryHandler) -> None:
    _HANDLERS[channel] = handler


def get_channel_handler(channel: str) -> DeliveryHandler | None:
    return _HANDLERS.get(channel)
