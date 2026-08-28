"""Bounded, deterministic exponential backoff for delivery retries (Phase 10
Block 4, section 4-6).

::

    delay_seconds = min(base_delay_seconds * 2 ** (attempt_number - 1), max_delay_seconds)

``attempt_number`` is the just-failed attempt's 1-based number (``Delivery.attempt_count``
at the moment ``complete_delivery_failure`` schedules the retry) — attempt 1
failing schedules ``base_delay_seconds``; attempt 2 failing doubles it to
``base_delay_seconds * 2``; attempt 3 quadruples it; and so on, capped at
``max_delay_seconds`` so a long-lived delivery never schedules an unbounded
wait.

No jitter is applied (section 6): jitter is optional per the Block 4
specification, and adding it here would either be non-deterministic (making
tests probabilistic, explicitly disallowed) or require its own injectable
source of randomness for no behavioral benefit this platform currently
needs. This is a deliberate simplicity choice, not an oversight — see the
Block 4 completion report.

Both bounds are server-owned settings only (section 4, 13) — never accepted
from client, model, provider, or ``Retry-After`` input.
"""

from __future__ import annotations

from django.conf import settings


def compute_retry_delay_seconds(
    *,
    attempt_number: int,
    base_delay_seconds: int | None = None,
    max_delay_seconds: int | None = None,
) -> int:
    base = int(
        base_delay_seconds
        if base_delay_seconds is not None
        else settings.DELIVERY_RETRY_BASE_DELAY_SECONDS
    )
    cap = int(
        max_delay_seconds
        if max_delay_seconds is not None
        else settings.DELIVERY_RETRY_MAX_DELAY_SECONDS
    )
    delay = base * (2 ** (attempt_number - 1))
    return int(min(delay, cap))
