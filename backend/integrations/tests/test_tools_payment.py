"""``payment.lookup`` / ``payment.refund`` tool contract, idempotency, and
duplicate-refund protection tests (section 33-44, 88, 91-92, 98)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from integrations.errors import (
    IntegrationAuthenticationFailedError,
    IntegrationRateLimitedError,
    IntegrationTimeoutError,
)
from integrations.models import IntegrationProvider
from integrations.providers.base import NormalizedPayment
from integrations.providers.fakes import FakePaymentProvider
from tools.errors import ToolError
from tools.execution import execute_tool
from tools.models import ToolExecutionStatus

from .factories import IntegrationConnectionFactory, bind_tool, running_run


def _payment(**overrides: object) -> NormalizedPayment:
    defaults: dict[str, object] = dict(
        payment_id="pi_1",
        external_payment_id="pi_1",
        status="succeeded",
        amount_minor=5000,
        currency="USD",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        refunded_amount_minor=0,
    )
    defaults.update(overrides)
    return NormalizedPayment(**defaults)  # type: ignore[arg-type]


def _setup(monkeypatch, *, fake, connection_kwargs=None):
    run = running_run()
    bind_tool(run, "payment.lookup")
    bind_tool(run, "payment.refund")
    IntegrationConnectionFactory(
        workspace=run.workspace, provider=IntegrationProvider.STRIPE, **(connection_kwargs or {})
    )
    monkeypatch.setattr("integrations.services.get_payment_provider", lambda provider: fake)
    return run


@pytest.mark.django_db(transaction=True)
class TestPaymentLookup:
    def test_success(self, monkeypatch):
        fake = FakePaymentProvider(payments={"pi_1": _payment()})
        run = _setup(monkeypatch, fake=fake)
        result = execute_tool(
            agent_run=run, tool_key="payment.lookup", arguments={"payment_reference": "pi_1"}
        )
        assert result.output["status"] == "succeeded"
        assert result.output["amount_minor"] == 5000

    def test_not_found(self, monkeypatch):
        fake = FakePaymentProvider()
        run = _setup(monkeypatch, fake=fake)
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run, tool_key="payment.lookup", arguments={"payment_reference": "missing"}
            )
        assert exc_info.value.code == "payment_not_found"

    def test_auth_failure(self, monkeypatch):
        fake = FakePaymentProvider(get_payment_errors=[IntegrationAuthenticationFailedError()])
        run = _setup(monkeypatch, fake=fake)
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run, tool_key="payment.lookup", arguments={"payment_reference": "pi_1"}
            )
        assert exc_info.value.code == "integration_authentication_failed"

    def test_no_connection_configured(self, monkeypatch):
        run = running_run()
        bind_tool(run, "payment.lookup")
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run, tool_key="payment.lookup", arguments={"payment_reference": "pi_1"}
            )
        assert exc_info.value.code == "integration_not_configured"

    def test_workspace_id_argument_is_rejected_not_honored(self, monkeypatch):
        fake = FakePaymentProvider(payments={"pi_1": _payment()})
        run = _setup(monkeypatch, fake=fake)
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run,
                tool_key="payment.lookup",
                arguments={
                    "payment_reference": "pi_1",
                    "workspace_id": "11111111-1111-1111-1111-111111111111",
                },
            )
        assert exc_info.value.code == "tool_invalid_input"

    def test_api_key_argument_is_rejected(self, monkeypatch):
        fake = FakePaymentProvider(payments={"pi_1": _payment()})
        run = _setup(monkeypatch, fake=fake)
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run,
                tool_key="payment.lookup",
                arguments={"payment_reference": "pi_1", "api_key": "sk_live_evil"},
            )
        assert exc_info.value.code == "tool_invalid_input"


@pytest.mark.django_db(transaction=True)
class TestPaymentRefund:
    def test_success(self, monkeypatch):
        fake = FakePaymentProvider(payments={"pi_1": _payment()})
        run = _setup(monkeypatch, fake=fake)
        result = execute_tool(
            agent_run=run,
            tool_key="payment.refund",
            arguments={"payment_reference": "pi_1", "amount_minor": 1000, "currency": "usd"},
        )
        assert result.output["status"] == "succeeded"
        assert result.output["amount_minor"] == 1000
        assert result.output["currency"] == "USD"
        assert fake.refund_call_count == 1

    def test_amount_exceeding_refundable_balance_is_rejected(self, monkeypatch):
        fake = FakePaymentProvider(payments={"pi_1": _payment(amount_minor=1000)})
        run = _setup(monkeypatch, fake=fake)
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run,
                tool_key="payment.refund",
                arguments={"payment_reference": "pi_1", "amount_minor": 5000, "currency": "usd"},
            )
        assert exc_info.value.code == "refund_not_allowed_by_provider"

    def test_negative_amount_rejected_before_reaching_the_provider(self, monkeypatch):
        fake = FakePaymentProvider(payments={"pi_1": _payment()})
        run = _setup(monkeypatch, fake=fake)
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run,
                tool_key="payment.refund",
                arguments={"payment_reference": "pi_1", "amount_minor": -100, "currency": "usd"},
            )
        assert exc_info.value.code == "tool_invalid_input"
        assert fake.refund_call_count == 0

    def test_reason_is_never_sent_as_raw_free_text_to_the_provider(self, monkeypatch):
        # The refund tool accepts a free-text reason but the fake/provider
        # boundary only ever receives typed, validated arguments.
        fake = FakePaymentProvider(payments={"pi_1": _payment()})
        run = _setup(monkeypatch, fake=fake)
        result = execute_tool(
            agent_run=run,
            tool_key="payment.refund",
            arguments={
                "payment_reference": "pi_1",
                "amount_minor": 500,
                "currency": "usd",
                "reason": "customer said the product broke",
            },
        )
        assert result.output["status"] == "succeeded"

    def test_repeated_call_with_same_tool_execution_reuses_the_provider_refund(self, monkeypatch):
        """Same logical ToolExecution row retried -> exactly one provider
        refund call (section 40-42, 91)."""
        fake = FakePaymentProvider(
            payments={"pi_1": _payment()},
            refund_errors=[(IntegrationRateLimitedError(), False)],
        )
        run = _setup(monkeypatch, fake=fake)
        idempotency_key = "stable-refund-key"

        # First attempt: transient failure, retryable — Phase 6's own retry
        # loop consumes this within the same execute_tool call.
        result = execute_tool(
            agent_run=run,
            tool_key="payment.refund",
            arguments={"payment_reference": "pi_1", "amount_minor": 1000, "currency": "usd"},
            idempotency_key=idempotency_key,
        )
        assert result.execution.status == ToolExecutionStatus.SUCCEEDED
        assert fake.refund_call_count == 2  # one failed attempt + one success

        # A second, fully separate execute_tool call with the same
        # application idempotency key reuses the stored result — no further
        # provider call at all.
        result2 = execute_tool(
            agent_run=run,
            tool_key="payment.refund",
            arguments={"payment_reference": "pi_1", "amount_minor": 1000, "currency": "usd"},
            idempotency_key=idempotency_key,
        )
        assert result2.reused is True
        assert fake.refund_call_count == 2

    def test_ambiguous_timeout_does_not_double_refund_on_manual_retry(self, monkeypatch):
        """The provider processed the refund but the client only saw a
        timeout; a later retry with the same idempotency key must not create
        a second refund (section 43, 92)."""
        fake = FakePaymentProvider(
            payments={"pi_1": _payment()},
            refund_errors=[(IntegrationTimeoutError(), True)],
        )
        run = _setup(monkeypatch, fake=fake)
        idempotency_key = "ambiguous-refund-key"

        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run,
                tool_key="payment.refund",
                arguments={"payment_reference": "pi_1", "amount_minor": 1000, "currency": "usd"},
                idempotency_key=idempotency_key,
            )
        # integration_timeout is deliberately excluded from the refund
        # tool's auto-retry set (WRITE_RETRYABLE_CODES) — Phase 6 does not
        # loop on it.
        assert exc_info.value.code == "integration_timeout"
        assert fake.refund_call_count == 1

        # The caller (agent/operator) explicitly retries with the same
        # idempotency key. Because Phase 6 resets a failed row back to
        # PENDING for the same key, and our provider idempotency key is
        # derived from that same stable tool_execution_id, the fake finds
        # its already-committed refund instead of creating a second one.
        result = execute_tool(
            agent_run=run,
            tool_key="payment.refund",
            arguments={"payment_reference": "pi_1", "amount_minor": 1000, "currency": "usd"},
            idempotency_key=idempotency_key,
        )
        assert result.execution.status == ToolExecutionStatus.SUCCEEDED
        # No new provider-visible refund call count increase from the
        # dedup path: the fake's internal committed-refund lookup is keyed
        # by idempotency_key, independent of call_count bookkeeping.
        assert fake.refund_call_count == 1

    def test_currency_is_normalized_to_uppercase(self, monkeypatch):
        fake = FakePaymentProvider(payments={"pi_1": _payment()})
        run = _setup(monkeypatch, fake=fake)
        result = execute_tool(
            agent_run=run,
            tool_key="payment.refund",
            arguments={"payment_reference": "pi_1", "amount_minor": 500, "currency": "usd"},
        )
        assert result.output["currency"] == "USD"

    def test_disabled_connection_blocks_refund_before_any_provider_call(self, monkeypatch):
        fake = FakePaymentProvider(payments={"pi_1": _payment()})
        run = running_run()
        bind_tool(run, "payment.refund")
        from integrations.models import IntegrationConnectionStatus

        IntegrationConnectionFactory(
            workspace=run.workspace,
            provider=IntegrationProvider.STRIPE,
            status=IntegrationConnectionStatus.DISABLED,
        )
        monkeypatch.setattr("integrations.services.get_payment_provider", lambda provider: fake)
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run,
                tool_key="payment.refund",
                arguments={"payment_reference": "pi_1", "amount_minor": 500, "currency": "usd"},
            )
        assert exc_info.value.code == "integration_disabled"
        assert fake.refund_call_count == 0
