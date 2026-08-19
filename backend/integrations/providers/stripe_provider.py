"""Stripe test-mode ``PaymentProvider`` adapter (section 36-44).

Phase 7 proves integration execution mechanics only — it never decides
*whether* a refund is authorized (that is Phase 8's deterministic policy +
approval engine). This adapter's only job is: talk to Stripe safely, map
every outcome to the normalized ``integrations.errors``/``providers.base``
types, and never let a ``stripe`` SDK object or exception cross the
boundary.

Test/sandbox only for Phase 7 (section 37, 90): the adapter itself does not
inspect the key's live/test-ness (Stripe secret keys are opaque to us), but
it is only ever constructed when ``INTEGRATIONS_LIVE_PROVIDERS_ENABLED`` is
set *and* the owning ``IntegrationConnection.environment == "test"`` is
enforced by ``integrations.services`` before a live key is ever accepted —
see ``validate_credentials_for_provider``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import stripe

# Private module, but it's the only public way to control per-client network
# timeouts on this pinned SDK version (see docstring in
# ``integrations.providers.factory`` for the version pin rationale).
from stripe._http_client import RequestsClient

from ..errors import (
    IntegrationAuthenticationFailedError,
    IntegrationInvalidRequestError,
    IntegrationMalformedResponseError,
    IntegrationPermissionDeniedError,
    IntegrationRateLimitedError,
    IntegrationTemporarilyUnavailableError,
    IntegrationTimeoutError,
    PaymentNotFoundError,
    RefundNotAllowedByProviderError,
)
from .base import NormalizedPayment, NormalizedRefund

#: Stripe's refund ``reason`` is a closed enum; anything else is simply
#: omitted rather than sent as free text (section 44 — no Stripe-rejected
#: value ever reaches the API call).
_STRIPE_REFUND_REASONS = frozenset({"duplicate", "fraudulent", "requested_by_customer"})


def _client(*, secret_key: str, timeout_seconds: float) -> stripe.StripeClient:
    return stripe.StripeClient(
        api_key=secret_key,
        http_client=RequestsClient(timeout=timeout_seconds),
        # Retries are handled at the Phase 6 tool-execution boundary with a
        # stable application idempotency key; the SDK must not also retry
        # independently (that would defeat the two-layer timeout design,
        # section 74-77).
        max_network_retries=0,
    )


def _map_error(exc: Exception) -> Exception:
    if isinstance(exc, stripe.AuthenticationError):
        return IntegrationAuthenticationFailedError()
    if isinstance(exc, stripe.PermissionError):
        return IntegrationPermissionDeniedError()
    if isinstance(exc, stripe.RateLimitError):
        return IntegrationRateLimitedError()
    if isinstance(exc, stripe.APIConnectionError):
        return IntegrationTimeoutError()
    if isinstance(exc, stripe.InvalidRequestError):
        if getattr(exc, "code", None) == "resource_missing":
            return PaymentNotFoundError()
        return IntegrationInvalidRequestError()
    if isinstance(exc, stripe.APIError):
        return IntegrationTemporarilyUnavailableError()
    if isinstance(exc, stripe.StripeError):
        return IntegrationTemporarilyUnavailableError()
    return IntegrationMalformedResponseError()


def _epoch_to_datetime(value: Any) -> datetime:
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError) as exc:
        raise IntegrationMalformedResponseError("Stripe returned an invalid timestamp.") from exc


class StripePaymentProvider:
    """Typed ``PaymentProvider`` backed by the real Stripe SDK (test mode)."""

    name = "stripe"

    def probe(self, *, credentials: dict, timeout_seconds: float) -> None:
        """Read-only connection-test probe (section 68-69): a balance
        retrieve is cheap and never mutates state."""
        secret_key = str(credentials.get("secret_key") or "")
        client = _client(secret_key=secret_key, timeout_seconds=timeout_seconds)
        try:
            client.v1.balance.retrieve()
        except stripe.StripeError as exc:
            raise _map_error(exc) from exc
        except Exception as exc:  # pragma: no cover - defensive, unexpected SDK failure
            raise IntegrationMalformedResponseError() from exc

    def get_payment(
        self, *, credentials: dict, payment_reference: str, timeout_seconds: float
    ) -> NormalizedPayment:
        secret_key = str(credentials.get("secret_key") or "")
        client = _client(secret_key=secret_key, timeout_seconds=timeout_seconds)
        try:
            intent = client.v1.payment_intents.retrieve(payment_reference)
        except stripe.StripeError as exc:
            raise _map_error(exc) from exc
        except Exception as exc:  # pragma: no cover - defensive, unexpected SDK failure
            raise IntegrationMalformedResponseError() from exc
        return self._normalize_payment(intent)

    def refund_payment(
        self,
        *,
        credentials: dict,
        payment_reference: str,
        amount_minor: int,
        currency: str,
        reason: str,
        idempotency_key: str,
        timeout_seconds: float,
    ) -> NormalizedRefund:
        secret_key = str(credentials.get("secret_key") or "")
        client = _client(secret_key=secret_key, timeout_seconds=timeout_seconds)
        params: dict[str, Any] = {
            "payment_intent": payment_reference,
            "amount": amount_minor,
        }
        if reason in _STRIPE_REFUND_REASONS:
            params["reason"] = reason
        try:
            # Stripe's generated ``RefundCreateParams`` TypedDict is stricter
            # than the plain dict this adapter builds above; the SDK accepts
            # a plain mapping at runtime (this is exercised by the SDK
            # boundary tests), so the static mismatch is safely ignored here
            # rather than importing/constructing the vendor TypedDict.
            refund = client.v1.refunds.create(
                params=params,  # type: ignore[arg-type]
                options={"idempotency_key": idempotency_key},
            )
        except stripe.InvalidRequestError as exc:
            if getattr(exc, "code", None) == "charge_already_refunded":
                raise RefundNotAllowedByProviderError(
                    "This payment has already been fully refunded."
                ) from exc
            raise _map_error(exc) from exc
        except stripe.StripeError as exc:
            raise _map_error(exc) from exc
        except Exception as exc:  # pragma: no cover - defensive, unexpected SDK failure
            raise IntegrationMalformedResponseError() from exc
        return NormalizedRefund(
            refund_id=refund.id,
            payment_id=str(refund.payment_intent),
            status=refund.status or "pending",
            amount_minor=refund.amount,
            currency=(refund.currency or currency).upper(),
            created_at=_epoch_to_datetime(refund.created),
            provider_request_id=refund.id,
        )

    def _normalize_payment(self, intent: Any) -> NormalizedPayment:
        try:
            return NormalizedPayment(
                payment_id=intent.id,
                external_payment_id=intent.id,
                status=str(intent.status),
                amount_minor=int(intent.amount),
                currency=str(intent.currency).upper(),
                created_at=_epoch_to_datetime(intent.created),
                # Stripe does not expose refunded-amount on a bare
                # PaymentIntent without expanding latest_charge; Phase 7
                # deliberately does not do a second round-trip for it here
                # (documented limitation — see docs/integrations.md).
                refunded_amount_minor=0,
                provider_request_id=intent.id,
            )
        except (AttributeError, ValueError, TypeError) as exc:
            raise IntegrationMalformedResponseError() from exc
