"""Stable, safe delivery-domain error taxonomy (Phase 10 Block 1)."""

from __future__ import annotations


class DeliveryError(Exception):
    code = "delivery_error"
    safe_message = "The delivery could not be processed."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.safe_message)
        if message:
            self.safe_message = message


class DeliveryNotFoundError(DeliveryError):
    code = "delivery_not_found"
    safe_message = "Delivery not found."


class DeliveryNotClaimableError(DeliveryError):
    """Raised when a claim attempt finds the delivery is not currently
    eligible: already claimed with an unexpired lease, not yet due, in a
    terminal state, or gone. Expected under normal concurrency (section 8,
    20) — callers treat this as a safe no-op, not an operational failure."""

    code = "delivery_not_claimable"
    safe_message = "This delivery is not currently claimable."


class StaleClaimError(DeliveryError):
    """Raised when a completion call's claim token no longer matches the
    delivery's active claim — the lease expired and another worker already
    reclaimed (and possibly completed) it (section 7, 15). Never overwrites
    the newer state; callers treat this as a safe no-op."""

    code = "delivery_stale_claim"
    safe_message = "This claim is no longer active."
