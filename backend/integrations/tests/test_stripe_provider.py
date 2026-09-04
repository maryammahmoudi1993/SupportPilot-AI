"""Stripe adapter SDK-boundary tests (section 36-44, 88-89).

Mocks the adapter's Stripe SDK boundary only (``stripe.StripeClient``) —
never the adapter's own mapping logic — so these tests verify the mapping
from vendor behavior to normalized domain behavior, per section 89.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import stripe

from integrations.errors import (
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
from integrations.providers.stripe_provider import StripePaymentProvider


class _FakeResource(SimpleNamespace):
    pass


class _FakeV1:
    def __init__(self, *, payment_intents=None, refunds=None, balance=None):
        self.payment_intents = payment_intents
        self.refunds = refunds
        self.balance = balance


class _FakeStripeClient:
    def __init__(self, v1) -> None:
        self.v1 = v1


@pytest.fixture
def provider() -> StripePaymentProvider:
    return StripePaymentProvider()


def _patch_client(monkeypatch, client) -> None:
    monkeypatch.setattr(
        "integrations.providers.stripe_provider.stripe.StripeClient", lambda **kwargs: client
    )


class TestGetPayment:
    def test_success_maps_fields(self, monkeypatch, provider):
        intent = _FakeResource(
            id="pi_1", status="succeeded", amount=1000, currency="usd", created=1700000000
        )
        client = _FakeStripeClient(
            _FakeV1(payment_intents=SimpleNamespace(retrieve=lambda ref: intent))
        )
        _patch_client(monkeypatch, client)
        payment = provider.get_payment(
            credentials={"secret_key": "sk_test_x"}, payment_reference="pi_1", timeout_seconds=5
        )
        assert payment.payment_id == "pi_1"
        assert payment.amount_minor == 1000
        assert payment.currency == "USD"
        assert payment.created_at == datetime.fromtimestamp(1700000000, tz=UTC)

    def test_not_found(self, monkeypatch, provider):
        def _raise(ref):
            raise stripe.InvalidRequestError(
                "no such payment_intent", param="id", code="resource_missing"
            )

        client = _FakeStripeClient(_FakeV1(payment_intents=SimpleNamespace(retrieve=_raise)))
        _patch_client(monkeypatch, client)
        with pytest.raises(PaymentNotFoundError):
            provider.get_payment(
                credentials={"secret_key": "sk_test_x"},
                payment_reference="missing",
                timeout_seconds=5,
            )

    def test_auth_failure(self, monkeypatch, provider):
        def _raise(ref):
            raise stripe.AuthenticationError("bad key")

        client = _FakeStripeClient(_FakeV1(payment_intents=SimpleNamespace(retrieve=_raise)))
        _patch_client(monkeypatch, client)
        with pytest.raises(IntegrationAuthenticationFailedError):
            provider.get_payment(
                credentials={"secret_key": "sk_test_bad"},
                payment_reference="pi_1",
                timeout_seconds=5,
            )

    def test_permission_denied(self, monkeypatch, provider):
        def _raise(ref):
            raise stripe.PermissionError("no access")

        client = _FakeStripeClient(_FakeV1(payment_intents=SimpleNamespace(retrieve=_raise)))
        _patch_client(monkeypatch, client)
        with pytest.raises(IntegrationPermissionDeniedError):
            provider.get_payment(
                credentials={"secret_key": "sk_test_x"}, payment_reference="pi_1", timeout_seconds=5
            )

    def test_rate_limited(self, monkeypatch, provider):
        def _raise(ref):
            raise stripe.RateLimitError("slow down")

        client = _FakeStripeClient(_FakeV1(payment_intents=SimpleNamespace(retrieve=_raise)))
        _patch_client(monkeypatch, client)
        with pytest.raises(IntegrationRateLimitedError):
            provider.get_payment(
                credentials={"secret_key": "sk_test_x"}, payment_reference="pi_1", timeout_seconds=5
            )

    def test_connection_error_maps_to_timeout(self, monkeypatch, provider):
        def _raise(ref):
            raise stripe.APIConnectionError("network down")

        client = _FakeStripeClient(_FakeV1(payment_intents=SimpleNamespace(retrieve=_raise)))
        _patch_client(monkeypatch, client)
        with pytest.raises(IntegrationTimeoutError):
            provider.get_payment(
                credentials={"secret_key": "sk_test_x"}, payment_reference="pi_1", timeout_seconds=5
            )

    def test_generic_invalid_request(self, monkeypatch, provider):
        def _raise(ref):
            raise stripe.InvalidRequestError("bad param", param="amount")

        client = _FakeStripeClient(_FakeV1(payment_intents=SimpleNamespace(retrieve=_raise)))
        _patch_client(monkeypatch, client)
        with pytest.raises(IntegrationInvalidRequestError):
            provider.get_payment(
                credentials={"secret_key": "sk_test_x"}, payment_reference="pi_1", timeout_seconds=5
            )

    def test_server_error_is_temporarily_unavailable(self, monkeypatch, provider):
        def _raise(ref):
            raise stripe.APIError("stripe is down")

        client = _FakeStripeClient(_FakeV1(payment_intents=SimpleNamespace(retrieve=_raise)))
        _patch_client(monkeypatch, client)
        with pytest.raises(IntegrationTemporarilyUnavailableError):
            provider.get_payment(
                credentials={"secret_key": "sk_test_x"}, payment_reference="pi_1", timeout_seconds=5
            )

    def test_malformed_response_becomes_a_safe_error_not_a_crash(self, monkeypatch, provider):
        # Missing expected attributes on the returned object.
        client = _FakeStripeClient(
            _FakeV1(payment_intents=SimpleNamespace(retrieve=lambda ref: object()))
        )
        _patch_client(monkeypatch, client)
        with pytest.raises(IntegrationMalformedResponseError):
            provider.get_payment(
                credentials={"secret_key": "sk_test_x"}, payment_reference="pi_1", timeout_seconds=5
            )

    def test_generic_stripe_error_is_temporarily_unavailable(self, monkeypatch, provider):
        def _raise(ref):
            raise stripe.IdempotencyError("duplicate idempotency key reused with new params")

        client = _FakeStripeClient(_FakeV1(payment_intents=SimpleNamespace(retrieve=_raise)))
        _patch_client(monkeypatch, client)
        with pytest.raises(IntegrationTemporarilyUnavailableError):
            provider.get_payment(
                credentials={"secret_key": "sk_test_x"}, payment_reference="pi_1", timeout_seconds=5
            )

    def test_invalid_timestamp_is_a_malformed_response(self, monkeypatch, provider):
        intent = _FakeResource(
            id="pi_1", status="succeeded", amount=1000, currency="usd", created="not-a-number"
        )
        client = _FakeStripeClient(
            _FakeV1(payment_intents=SimpleNamespace(retrieve=lambda ref: intent))
        )
        _patch_client(monkeypatch, client)
        with pytest.raises(IntegrationMalformedResponseError):
            provider.get_payment(
                credentials={"secret_key": "sk_test_x"}, payment_reference="pi_1", timeout_seconds=5
            )

    def test_unexpected_sdk_exception_is_contained(self, monkeypatch, provider):
        def _raise(ref):
            raise RuntimeError("unexpected SDK bug")

        client = _FakeStripeClient(_FakeV1(payment_intents=SimpleNamespace(retrieve=_raise)))
        _patch_client(monkeypatch, client)
        with pytest.raises(IntegrationMalformedResponseError):
            provider.get_payment(
                credentials={"secret_key": "sk_test_x"}, payment_reference="pi_1", timeout_seconds=5
            )


class TestRefundPayment:
    def test_success_maps_fields(self, monkeypatch, provider):
        refund = _FakeResource(
            id="re_1",
            payment_intent="pi_1",
            status="succeeded",
            amount=500,
            currency="usd",
            created=1700000000,
        )
        client = _FakeStripeClient(
            _FakeV1(refunds=SimpleNamespace(create=lambda params, options: refund))
        )
        _patch_client(monkeypatch, client)
        result = provider.refund_payment(
            credentials={"secret_key": "sk_test_x"},
            payment_reference="pi_1",
            amount_minor=500,
            currency="USD",
            reason="requested_by_customer",
            idempotency_key="key-1",
            timeout_seconds=5,
        )
        assert result.refund_id == "re_1"
        assert result.amount_minor == 500

    def test_already_refunded_is_normalized(self, monkeypatch, provider):
        def _raise(params, options):
            raise stripe.InvalidRequestError(
                "already refunded", param=None, code="charge_already_refunded"
            )

        client = _FakeStripeClient(_FakeV1(refunds=SimpleNamespace(create=_raise)))
        _patch_client(monkeypatch, client)
        with pytest.raises(RefundNotAllowedByProviderError):
            provider.refund_payment(
                credentials={"secret_key": "sk_test_x"},
                payment_reference="pi_1",
                amount_minor=500,
                currency="USD",
                reason="requested_by_customer",
                idempotency_key="key-1",
                timeout_seconds=5,
            )

    def test_generic_invalid_request_during_refund_is_mapped(self, monkeypatch, provider):
        def _raise(params, options):
            raise stripe.InvalidRequestError("bad amount", param="amount")

        client = _FakeStripeClient(_FakeV1(refunds=SimpleNamespace(create=_raise)))
        _patch_client(monkeypatch, client)
        with pytest.raises(IntegrationInvalidRequestError):
            provider.refund_payment(
                credentials={"secret_key": "sk_test_x"},
                payment_reference="pi_1",
                amount_minor=500,
                currency="USD",
                reason="requested_by_customer",
                idempotency_key="key-1",
                timeout_seconds=5,
            )

    def test_generic_stripe_error_during_refund_is_mapped(self, monkeypatch, provider):
        def _raise(params, options):
            raise stripe.RateLimitError("slow down")

        client = _FakeStripeClient(_FakeV1(refunds=SimpleNamespace(create=_raise)))
        _patch_client(monkeypatch, client)
        with pytest.raises(IntegrationRateLimitedError):
            provider.refund_payment(
                credentials={"secret_key": "sk_test_x"},
                payment_reference="pi_1",
                amount_minor=500,
                currency="USD",
                reason="requested_by_customer",
                idempotency_key="key-1",
                timeout_seconds=5,
            )

    def test_invalid_reason_is_never_sent_to_stripe(self, monkeypatch, provider):
        captured = {}

        def _create(params, options):
            captured.update(params)
            return _FakeResource(
                id="re_1",
                payment_intent="pi_1",
                status="succeeded",
                amount=500,
                currency="usd",
                created=1700000000,
            )

        client = _FakeStripeClient(_FakeV1(refunds=SimpleNamespace(create=_create)))
        _patch_client(monkeypatch, client)
        provider.refund_payment(
            credentials={"secret_key": "sk_test_x"},
            payment_reference="pi_1",
            amount_minor=500,
            currency="USD",
            reason="not a real stripe reason",
            idempotency_key="key-1",
            timeout_seconds=5,
        )
        assert "reason" not in captured


class TestProbe:
    def test_probe_success(self, monkeypatch, provider):
        client = _FakeStripeClient(_FakeV1(balance=SimpleNamespace(retrieve=lambda: object())))
        _patch_client(monkeypatch, client)
        provider.probe(credentials={"secret_key": "sk_test_x"}, timeout_seconds=5)

    def test_probe_maps_auth_failure(self, monkeypatch, provider):
        def _raise():
            raise stripe.AuthenticationError("bad key")

        client = _FakeStripeClient(_FakeV1(balance=SimpleNamespace(retrieve=_raise)))
        _patch_client(monkeypatch, client)
        with pytest.raises(IntegrationAuthenticationFailedError):
            provider.probe(credentials={"secret_key": "sk_test_bad"}, timeout_seconds=5)

    def test_raw_vendor_exception_message_never_becomes_the_safe_message(
        self, monkeypatch, provider
    ):
        # Phase 15 Security Checkpoint 5 (Part D.4): the underlying Stripe
        # SDK exception's message text (which could echo back a
        # credential-looking string) must never flow into the normalized
        # error's `safe_message` — `_map_error()` always constructs the
        # normalized error with no message argument, so `safe_message`
        # stays each class's fixed default.
        marker = "PHASE15_SECRET_KEY_MARKER_do-not-leak"

        def _raise(ref):
            raise stripe.AuthenticationError(f"invalid api key: {marker}")

        client = _FakeStripeClient(_FakeV1(payment_intents=SimpleNamespace(retrieve=_raise)))
        _patch_client(monkeypatch, client)
        with pytest.raises(IntegrationAuthenticationFailedError) as exc_info:
            provider.get_payment(
                credentials={"secret_key": "sk_test_x"}, payment_reference="pi_1", timeout_seconds=5
            )

        assert marker not in exc_info.value.safe_message
        assert exc_info.value.safe_message == "The provider rejected the configured credentials."
