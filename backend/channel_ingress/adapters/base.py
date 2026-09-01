"""The typed inbound channel adapter protocol (Phase 13 section 14).

A Django view never parses one vendor's payload shape directly — it resolves
the endpoint, hands the adapter the raw bytes/headers, and receives back
exactly one ``CanonicalInboundMessage``. Every adapter implements the same
three-step boundary in the same order:

1. ``verify_signature`` — authenticate the *transport delivery* before any
   parsed content is trusted (section 19). Raises a
   ``channel_ingress.errors.ChannelIngressError`` subclass on failure; never
   returns a boolean callers might forget to check.
2. ``parse_event`` — minimal, bounded structural parsing only (section 22-23:
   no unbounded recursive deserialization).
3. ``normalize`` — maps the parsed structure onto ``CanonicalInboundMessage``.
   Provider-specific field names/quirks terminate here (section 7); nothing
   downstream ever sees them again.

Real tests use the deterministic fakes in ``channel_ingress/tests/fakes.py``
(section 14, 64) — never a live provider call.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from .. import models
from ..schemas import CanonicalInboundMessage


class ChannelAdapter(Protocol):
    #: The bounded ``ChannelType`` value this adapter handles.
    channel: str

    def verify_signature(
        self, *, endpoint: models.ChannelEndpoint, raw_body: bytes, headers: Mapping[str, str]
    ) -> None: ...

    def parse_event(self, *, raw_body: bytes) -> dict: ...

    def normalize(
        self, *, endpoint: models.ChannelEndpoint, parsed: dict
    ) -> CanonicalInboundMessage: ...
