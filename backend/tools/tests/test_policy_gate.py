"""Direct coverage of the Phase 8 policy gate's DENY, fail-closed, and
idempotency-replay branches inside ``tools.execution`` (section 27-29, 60,
98-100)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from approvals.models import ApprovalRequest
from integrations.models import IntegrationProvider
from integrations.providers.base import NormalizedPayment
from integrations.providers.fakes import FakePaymentProvider
from integrations.tests.factories import IntegrationConnectionFactory, bind_tool, running_run
from policies.models import PolicyEffect
from policies.tests.factories import active_version_with_rules
from tools.errors import (
    ToolApprovalRequiredError,
    ToolPolicyDeniedError,
    ToolPolicyEvaluationFailedError,
)
from tools.execution import execute_tool
from tools.models import ToolExecution, ToolExecutionStatus


def _payment(**overrides):
    defaults = dict(
        payment_id="pi_1",
        external_payment_id="pi_1",
        status="succeeded",
        amount_minor=1_000_000,
        currency="USD",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        refunded_amount_minor=0,
    )
    defaults.update(overrides)
    return NormalizedPayment(**defaults)


@pytest.mark.django_db(transaction=True)
class TestDenyPath:
    def _setup(self, monkeypatch, *, amount_minor=1_000_000):
        run = running_run()
        bind_tool(run, "payment.refund")
        IntegrationConnectionFactory(workspace=run.workspace, provider=IntegrationProvider.STRIPE)
        fake = FakePaymentProvider(payments={"pi_1": _payment()})
        monkeypatch.setattr("integrations.services.get_payment_provider", lambda provider: fake)
        return run, fake, amount_minor

    def test_refund_above_maximum_is_denied_and_handler_never_runs(self, monkeypatch, settings):
        settings.POLICIES_DEFAULT_REFUND_APPROVAL_MAX_MINOR = 50000
        run, fake, amount_minor = self._setup(monkeypatch, amount_minor=100000)
        with pytest.raises(ToolPolicyDeniedError):
            execute_tool(
                agent_run=run,
                tool_key="payment.refund",
                arguments={
                    "payment_reference": "pi_1",
                    "amount_minor": amount_minor,
                    "currency": "usd",
                },
            )
        assert fake.refund_call_count == 0
        execution = ToolExecution.objects.get(agent_run=run)
        assert execution.status == ToolExecutionStatus.BLOCKED_BY_POLICY
        assert execution.error_code == "policy_action_denied"
        assert not ApprovalRequest.objects.filter(tool_execution=execution).exists()

    def test_retry_with_same_idempotency_key_replays_the_stored_denial(self, monkeypatch, settings):
        settings.POLICIES_DEFAULT_REFUND_APPROVAL_MAX_MINOR = 50000
        run, fake, amount_minor = self._setup(monkeypatch, amount_minor=100000)
        args = {"payment_reference": "pi_1", "amount_minor": amount_minor, "currency": "usd"}
        with pytest.raises(ToolPolicyDeniedError):
            execute_tool(
                agent_run=run, tool_key="payment.refund", arguments=args, idempotency_key="k1"
            )
        with pytest.raises(ToolPolicyDeniedError):
            execute_tool(
                agent_run=run, tool_key="payment.refund", arguments=args, idempotency_key="k1"
            )
        assert fake.refund_call_count == 0
        # Only one RiskAssessment/PolicyEvaluation was ever created for this
        # execution row — the replay never re-entered the gate.
        execution = ToolExecution.objects.get(agent_run=run)
        from policies.models import PolicyEvaluation

        assert PolicyEvaluation.objects.filter(tool_execution=execution).count() == 1


@pytest.mark.django_db(transaction=True)
class TestFailClosed:
    def test_unknown_predicate_in_workspace_rule_denies_and_never_calls_handler(self, monkeypatch):
        run, fake, amount_minor = TestDenyPath()._setup(monkeypatch, amount_minor=1000)
        active_version_with_rules(
            workspace=run.workspace,
            rules=[
                dict(
                    name="corrupt",
                    tool_key="payment.refund",
                    effect=PolicyEffect.ALLOW,
                    condition_config={"all": [{"predicate": "does_not_exist"}]},
                )
            ],
        )
        with pytest.raises(ToolPolicyEvaluationFailedError):
            execute_tool(
                agent_run=run,
                tool_key="payment.refund",
                arguments={
                    "payment_reference": "pi_1",
                    "amount_minor": amount_minor,
                    "currency": "usd",
                },
            )
        assert fake.refund_call_count == 0
        execution = ToolExecution.objects.get(agent_run=run)
        assert execution.status == ToolExecutionStatus.BLOCKED_BY_POLICY
        from policies.models import PolicyEvaluation

        evaluation = PolicyEvaluation.objects.get(tool_execution=execution)
        assert evaluation.decision == PolicyEffect.DENY
        assert evaluation.decision_code == "policy_evaluation_failed"


@pytest.mark.django_db(transaction=True)
class TestApprovalRequiredRetry:
    def test_retry_with_same_idempotency_key_while_pending_reraises_approval_required(
        self, monkeypatch
    ):
        run, fake, amount_minor = TestDenyPath()._setup(monkeypatch, amount_minor=10000)
        args = {"payment_reference": "pi_1", "amount_minor": amount_minor, "currency": "usd"}
        with pytest.raises(ToolApprovalRequiredError):
            execute_tool(
                agent_run=run, tool_key="payment.refund", arguments=args, idempotency_key="k1"
            )
        with pytest.raises(ToolApprovalRequiredError):
            execute_tool(
                agent_run=run, tool_key="payment.refund", arguments=args, idempotency_key="k1"
            )
        execution = ToolExecution.objects.get(agent_run=run)
        assert ApprovalRequest.objects.filter(tool_execution=execution).count() == 1
