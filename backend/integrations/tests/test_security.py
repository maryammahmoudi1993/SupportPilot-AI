"""Security regression tests: secret redaction, argument/workspace/
connection spoofing, and log/trace leakage (section 19, 105-108)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from common.redaction import redact
from integrations.errors import IntegrationAuthenticationFailedError
from integrations.models import IntegrationProvider
from integrations.providers.base import NormalizedPayment
from integrations.providers.fakes import FakePaymentProvider
from tools.errors import ToolError
from tools.execution import execute_tool
from tools.models import ToolExecution

from .factories import IntegrationConnectionFactory, bind_tool, running_run


class TestRedactionMarkers:
    @pytest.mark.parametrize(
        "key",
        ["stripe_key", "webhook_secret", "client_secret", "refresh_token", "encryption_key"],
    )
    def test_provider_style_secret_keys_are_redacted(self, key):
        redacted = redact({key: "sk_test_super_secret_123"})
        assert redacted[key] == "***REDACTED***"

    def test_nested_secret_is_redacted(self):
        # "credentials" itself matches the "credential" marker, so the whole
        # nested value is redacted at that level — never partially exposed.
        redacted = redact({"credentials": {"secret_key": "sk_test_abc"}})
        assert redacted["credentials"] == "***REDACTED***"

    def test_secret_nested_under_a_non_sensitive_key_is_still_redacted(self):
        redacted = redact({"payload": {"secret_key": "sk_test_abc"}})
        assert redacted["payload"]["secret_key"] == "***REDACTED***"


@pytest.mark.django_db
class TestToolArgumentSecretInjection:
    def test_extra_secret_field_is_rejected_by_strict_schema(self):
        run = running_run()
        bind_tool(run, "payment.lookup")
        IntegrationConnectionFactory(workspace=run.workspace, provider=IntegrationProvider.STRIPE)
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run,
                tool_key="payment.lookup",
                arguments={"payment_reference": "pi_1", "api_key": "sk_live_evil_injected"},
            )
        assert exc_info.value.code == "tool_invalid_input"
        assert not ToolExecution.objects.filter(agent_run=run).exists()


@pytest.mark.django_db(transaction=True)
class TestProviderSecretNeverLeaks:
    def test_provider_error_message_never_leaks_into_tool_execution(self, monkeypatch):
        run = running_run()
        bind_tool(run, "payment.lookup")
        IntegrationConnectionFactory(workspace=run.workspace, provider=IntegrationProvider.STRIPE)
        leaking_error = IntegrationAuthenticationFailedError()
        fake = FakePaymentProvider(get_payment_errors=[leaking_error])
        monkeypatch.setattr("integrations.services.get_payment_provider", lambda provider: fake)

        with pytest.raises(ToolError):
            execute_tool(
                agent_run=run, tool_key="payment.lookup", arguments={"payment_reference": "pi_1"}
            )

        execution = ToolExecution.objects.get(agent_run=run)
        assert "sk_test" not in execution.error_message_safe
        assert execution.error_code == "integration_authentication_failed"

    def test_successful_result_never_contains_credential_material(self, monkeypatch):
        run = running_run()
        bind_tool(run, "payment.lookup")
        IntegrationConnectionFactory(workspace=run.workspace, provider=IntegrationProvider.STRIPE)
        fake = FakePaymentProvider(
            payments={
                "pi_1": NormalizedPayment(
                    payment_id="pi_1",
                    external_payment_id="pi_1",
                    status="succeeded",
                    amount_minor=1000,
                    currency="USD",
                    created_at=datetime(2024, 1, 1, tzinfo=UTC),
                )
            }
        )
        monkeypatch.setattr("integrations.services.get_payment_provider", lambda provider: fake)
        execute_tool(
            agent_run=run, tool_key="payment.lookup", arguments={"payment_reference": "pi_1"}
        )
        execution = ToolExecution.objects.get(agent_run=run)
        assert "sk_test" not in str(execution.result_redacted)


@pytest.mark.django_db
class TestSpoofingAttempts:
    def test_workspace_id_in_arguments_never_reaches_the_handler(self):
        run = running_run()
        bind_tool(run, "customer.lookup")
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run,
                tool_key="customer.lookup",
                arguments={
                    "email": "a@example.com",
                    "workspace_id": "11111111-1111-1111-1111-111111111111",
                },
            )
        assert exc_info.value.code == "tool_invalid_input"

    def test_no_tool_accepts_a_connection_identifier_argument(self):
        """Every business tool's input schema is a closed (``extra="forbid"``)
        model with no connection/provider-selection field at all — connection
        resolution is always server-side (section 70, 108)."""
        from integrations.tools import ALL_INTEGRATION_TOOLS

        for tool in ALL_INTEGRATION_TOOLS:
            fields = tool.spec.input_model.model_fields
            assert "connection_id" not in fields
            assert "integration_connection_id" not in fields
