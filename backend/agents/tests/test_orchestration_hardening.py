"""Phase 9 Block 6: adversarial security, full-stack concurrency, and
end-to-end hardening (section 0-135).

Blocks 1-5 already carry deep unit/service/API coverage for tenant
isolation, prompt-injection boundaries, budgets, idempotent replay, and the
approval/handoff races taken individually (see
``docs/architecture/block6-hardening-matrix.md`` for the full mapping).
This module adds only the genuinely new full-stack surface Block 6's
adversarial pass identified as uncovered:

* real multi-threaded (not merely sequential-replay) races through the
  actual orchestration/approval/handoff services, backed by PostgreSQL
  row locks rather than test-only serialization;
* the one full end-to-end flow combination Block 5 did not yet exercise —
  approval-then-handoff in the same run (section 83);
* a live-RBAC-at-decision-time regression (section 95);
* an orchestration-level (not just registry-level) dangerous-tool attack;
* a secret-leakage check against a real stored integration credential
  reaching a ``HumanHandoff``.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

import pytest
from django.db import connections, transaction

from accounts.tests.factories import UserFactory
from agents import orchestration, services
from agents.errors import AgentRunNotCancellableError
from agents.models import AgentRunStatus
from agents.providers.errors import ProviderRateLimitedError
from agents.providers.fake import DeterministicFakeLLMProvider, FakeLLMScenario
from agents.providers.schemas import NormalizedHandoffRequest, NormalizedToolCall
from approvals.models import ApprovalDecisionValue, ApprovalRequest, ApprovalStatus
from approvals.services import decide_approval
from approvals.tests.factories import pending_refund_approval
from conversations.models import Message, MessageSenderType
from conversations.tests.factories import ConversationFactory
from integrations.models import IntegrationProvider
from integrations.providers.base import NormalizedPayment
from integrations.providers.fakes import FakePaymentProvider
from integrations.tests.factories import IntegrationConnectionFactory, bind_tool
from tickets.models import HumanHandoff, HumanHandoffReason, HumanHandoffStatus
from tools.execution import resume_after_approval
from tools.models import ToolExecution
from tools.tests.factories import ToolBindingFactory, ToolDefinitionFactory
from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceMembershipFactory

from .factories import AgentRunFactory, PublishedAgentVersionFactory


def _provider(monkeypatch, scenarios):
    provider = DeterministicFakeLLMProvider(scenarios)
    monkeypatch.setattr(services, "get_llm_provider", lambda: provider)
    return provider


def _bind(version, key):
    definition = ToolDefinitionFactory(key=key, handler_key=key)
    ToolBindingFactory(agent_version=version, tool_definition=definition)


def _run_with_conversation(**overrides):
    version = overrides.pop("agent_version", None) or PublishedAgentVersionFactory(
        max_model_calls=3, max_tool_calls=3
    )
    conversation = overrides.pop("conversation", None) or ConversationFactory(
        workspace=version.agent_definition.workspace
    )
    return AgentRunFactory(
        agent_version=version,
        workspace=version.agent_definition.workspace,
        conversation=conversation,
        **overrides,
    )


def _run_in_threads(*targets):
    threads = [threading.Thread(target=t) for t in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


# ---------------------------------------------------------------------------
# Full-stack concurrency races (section 27-38, 106, 128-129) — real threads
# against real PostgreSQL row locks, not sequential replay.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestFullStackConcurrencyRaces:
    def test_two_workers_claiming_the_same_pending_run_execute_the_model_once(self, monkeypatch):
        provider = _provider(monkeypatch, FakeLLMScenario(response="answer"))
        run = AgentRunFactory()

        errors = []

        def _execute():
            try:
                services.execute_agent_run(run.id)
            except Exception as exc:  # noqa: BLE001 - captured for assertion
                errors.append(exc)
            finally:
                connections.close_all()

        _run_in_threads(_execute, _execute)

        assert not errors
        assert provider.call_count == 1
        run.refresh_from_db()
        assert run.status == AgentRunStatus.SUCCEEDED
        assert Message.objects.filter(
            conversation=run.conversation, sender_type=MessageSenderType.AI_AGENT
        ).count() == (1 if run.conversation_id else 0)

    def test_duplicate_refund_resume_delivery_executes_the_provider_once(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        approver = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        decide_approval(
            workspace=run.workspace,
            approval_request=ApprovalRequest.objects.get(pk=approval.pk),
            actor=approver.user,
            actor_role=approver.role,
            decision=ApprovalDecisionValue.APPROVE,
        )

        errors = []

        def _resume():
            try:
                resume_after_approval(tool_execution_id=str(approval.tool_execution_id))
            except Exception as exc:  # noqa: BLE001 - one thread's replay-visible
                # outcome (ToolAlreadyResolvedError-style) is expected; only an
                # unexpected exception type would indicate a real defect, and
                # the fake provider's call count is the authoritative check.
                errors.append(exc)
            finally:
                connections.close_all()

        _run_in_threads(_resume, _resume)

        assert fake.refund_call_count == 1

    def test_double_handoff_completion_delivery_creates_one_handoff_and_message(self):
        run = _run_with_conversation(status=AgentRunStatus.RUNNING)
        result = {
            "model_call_count": 1,
            "step_count": 1,
            "handoff_request": {
                "reason_code": HumanHandoffReason.CUSTOMER_REQUESTED,
                "summary": "Wants a human.",
            },
        }

        errors = []

        def _complete():
            try:
                with transaction.atomic():
                    services._complete_run_as_handoff(run, result)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                connections.close_all()

        _run_in_threads(_complete, _complete)

        assert not errors
        assert HumanHandoff.objects.filter(conversation=run.conversation).count() == 1
        assert (
            Message.objects.filter(
                conversation=run.conversation, sender_type=MessageSenderType.AI_AGENT
            ).count()
            == 1
        )
        run.refresh_from_db()
        assert run.status == AgentRunStatus.HANDED_OFF

    def test_handoff_vs_cancel_race_is_never_incoherent(self):
        run = _run_with_conversation(status=AgentRunStatus.RUNNING)
        result = {
            "model_call_count": 1,
            "step_count": 1,
            "handoff_request": {
                "reason_code": HumanHandoffReason.CUSTOMER_REQUESTED,
                "summary": "Wants a human.",
            },
        }
        errors = []

        def _complete():
            try:
                services._complete_run_as_handoff(run, result)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                connections.close_all()

        def _cancel():
            try:
                services.cancel_agent_run(workspace=run.workspace, run=run, actor=UserFactory())
            except AgentRunNotCancellableError:
                pass  # the other side already won the row lock — expected
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                connections.close_all()

        _run_in_threads(_complete, _cancel)

        assert not errors
        run.refresh_from_db()
        assert run.status in (AgentRunStatus.HANDED_OFF, AgentRunStatus.CANCELLED)
        active_handoffs = HumanHandoff.objects.filter(
            conversation=run.conversation,
            status__in=[HumanHandoffStatus.PENDING, HumanHandoffStatus.ASSIGNED],
        ).count()
        if run.status == AgentRunStatus.CANCELLED:
            # Cancellation won the lock first: the handoff attempt must have
            # observed the non-RUNNING run and returned without creating one,
            # and never leave an active handoff dangling off a cancelled run.
            assert active_handoffs == 0
        else:
            # The handoff committed first: cancellation must have then hit
            # the terminal-state guard, never silently reopening HANDED_OFF.
            assert active_handoffs == 1

    def test_approve_vs_cancel_race_through_full_orchestration_is_coherent(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        from agents.models import AgentRun as _AgentRun

        _AgentRun.objects.filter(pk=run.pk).update(status=AgentRunStatus.WAITING_FOR_APPROVAL)
        approver = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        # Suppress the real dispatch so both continuations happen inline on
        # these two threads rather than racing an actual Celery worker.
        import approvals.services as approvals_services

        monkeypatch.setattr(approvals_services, "_dispatch_resume", lambda approval_id: None)
        errors = []

        def _approve():
            try:
                decide_approval(
                    workspace=run.workspace,
                    approval_request=ApprovalRequest.objects.get(pk=approval.pk),
                    actor=approver.user,
                    actor_role=approver.role,
                    decision=ApprovalDecisionValue.APPROVE,
                )
                orchestration.resume_support_agent_run(str(approval.id))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                connections.close_all()

        def _cancel():
            try:
                services.cancel_agent_run(
                    workspace=run.workspace,
                    run=_AgentRun.objects.get(pk=run.pk),
                    actor=UserFactory(),
                )
            except AgentRunNotCancellableError:
                pass
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                connections.close_all()

        _run_in_threads(_approve, _cancel)

        assert not errors
        # Whichever side won, the refund provider must never have been
        # called for a run that ended up CANCELLED (Block 4's fix,
        # reconfirmed here under real full-orchestration concurrency).
        run.refresh_from_db()
        if run.status == AgentRunStatus.CANCELLED:
            assert fake.refund_call_count == 0
        assert fake.refund_call_count <= 1


# ---------------------------------------------------------------------------
# End-to-end scenario K — approval then handoff in the same run
# (section 83, 131).
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestE2EScenarioKApprovalThenHandoff:
    def test_refund_executes_then_a_later_turn_requests_handoff(self, monkeypatch):
        conversation = ConversationFactory()
        version = PublishedAgentVersionFactory(
            agent_definition__workspace=conversation.workspace, max_model_calls=3, max_tool_calls=2
        )
        run = AgentRunFactory(
            agent_version=version,
            workspace=version.agent_definition.workspace,
            conversation=conversation,
        )
        bind_tool(run, "payment.refund")
        IntegrationConnectionFactory(workspace=run.workspace, provider=IntegrationProvider.STRIPE)
        payment = NormalizedPayment(
            payment_id="pi_1",
            external_payment_id="pi_1",
            status="succeeded",
            amount_minor=1_000_000,
            currency="USD",
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
            refunded_amount_minor=0,
        )
        fake = FakePaymentProvider(payments={"pi_1": payment})
        monkeypatch.setattr("integrations.services.get_payment_provider", lambda provider: fake)

        provider = _provider(
            monkeypatch,
            [
                FakeLLMScenario(
                    tool_calls=(
                        NormalizedToolCall(
                            call_id="1",
                            tool_name="payment.refund",
                            arguments={
                                "payment_reference": "pi_1",
                                "amount_minor": 10_000,
                                "currency": "usd",
                            },
                        ),
                    )
                ),
                FakeLLMScenario(
                    response="",
                    handoff_request=NormalizedHandoffRequest(
                        reason_code=HumanHandoffReason.CUSTOMER_REQUESTED,
                        summary="Wants to speak to a person about this refund.",
                    ),
                ),
            ],
        )

        first = orchestration.execute_support_agent_run(run.id)
        assert first.status == AgentRunStatus.WAITING_FOR_APPROVAL
        assert fake.refund_call_count == 0

        approval = ApprovalRequest.objects.get(tool_execution__agent_run=run)
        approver = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        import approvals.services as approvals_services

        monkeypatch.setattr(approvals_services, "_dispatch_resume", lambda approval_id: None)
        decide_approval(
            workspace=run.workspace,
            approval_request=approval,
            actor=approver.user,
            actor_role=approver.role,
            decision=ApprovalDecisionValue.APPROVE,
        )

        final_status = orchestration.resume_support_agent_run(str(approval.id))

        assert final_status == AgentRunStatus.HANDED_OFF
        assert fake.refund_call_count == 1
        assert HumanHandoff.objects.filter(conversation=conversation).count() == 1
        assert provider.call_count == 2  # no extra model call for the acknowledgement
        run.refresh_from_db()
        assert run.status == AgentRunStatus.HANDED_OFF
        assert run.output_message_id is not None
        # The refund's own tool result never became a second customer-facing
        # message — the handoff acknowledgement is the run's one terminal
        # message, per the OneToOne output_message invariant.
        assert (
            Message.objects.filter(
                conversation=conversation, sender_type=MessageSenderType.AI_AGENT
            ).count()
            == 1
        )
        assert ToolExecution.objects.filter(agent_run=run).count() == 1


# ---------------------------------------------------------------------------
# Stale-role regression (section 95).
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestStaleRoleAtDecisionTime:
    def test_a_membership_demoted_after_approval_creation_uses_the_live_role(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        membership = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        # Demote after the approval already exists — the caller must not be
        # able to rely on a role captured earlier (e.g. at JWT issuance);
        # the service re-reads live DB membership on every call.
        membership.role = WorkspaceRole.SUPPORT_AGENT
        membership.save()

        from approvals.errors import ApprovalPermissionDeniedError

        with pytest.raises(ApprovalPermissionDeniedError):
            decide_approval(
                workspace=run.workspace,
                approval_request=ApprovalRequest.objects.get(pk=approval.pk),
                actor=membership.user,
                actor_role=membership.role,
                decision=ApprovalDecisionValue.APPROVE,
            )
        assert fake.refund_call_count == 0
        approval.refresh_from_db()
        assert approval.status == ApprovalStatus.PENDING


# ---------------------------------------------------------------------------
# Orchestration-level dangerous/unknown tool attack (section 21, 105).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDangerousUnknownToolFullOrchestration:
    @pytest.mark.parametrize(
        "dangerous_key",
        ["system.shell", "python.exec", "sql.execute", "http.request", "filesystem.delete"],
    )
    def test_a_dangerous_tool_name_never_has_a_registered_handler_and_fails_safely(
        self, monkeypatch, dangerous_key
    ):
        version = PublishedAgentVersionFactory(max_model_calls=2, max_tool_calls=1)
        run = AgentRunFactory(agent_version=version, workspace=version.agent_definition.workspace)
        provider = _provider(
            monkeypatch,
            [
                FakeLLMScenario(
                    tool_calls=(
                        NormalizedToolCall(
                            call_id="1", tool_name=dangerous_key, arguments={"cmd": "rm -rf /"}
                        ),
                    )
                ),
                FakeLLMScenario(response="I cannot do that."),
            ],
        )

        result = services.execute_agent_run(run.id)

        assert result.status == AgentRunStatus.SUCCEEDED
        assert result.tool_call_count == 0
        assert not ToolExecution.objects.filter(agent_run=run).exists()
        assert "tool_not_registered" in provider.requests[1].messages[-1].content


# ---------------------------------------------------------------------------
# Secret leakage across a real HumanHandoff surface (section 25, 105).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSecretLeakageIntoHandoffSurfaces:
    def test_a_real_stored_integration_secret_never_reaches_a_handoff(self, monkeypatch):
        run = _run_with_conversation(status=AgentRunStatus.RUNNING)
        connection = IntegrationConnectionFactory(
            workspace=run.workspace, provider=IntegrationProvider.STRIPE
        )
        # The provider's own retryable failure classifies to a runtime
        # handoff (Block 5) — verify the escalation summary never echoes
        # back the connection's stored secret material.
        provider = _provider(
            monkeypatch,
            FakeLLMScenario(error=ProviderRateLimitedError, error_message="provider unavailable"),
        )
        result = services.execute_claimed_agent_run(run)

        secret_material = connection.encrypted_credentials
        assert secret_material  # sanity: a real ciphertext exists on this row

        for handoff in HumanHandoff.objects.filter(conversation=run.conversation):
            assert str(secret_material) not in handoff.safe_summary
        for message in Message.objects.filter(conversation=run.conversation):
            assert str(secret_material) not in message.body
        assert provider.call_count >= 1
        assert result.status in (AgentRunStatus.HANDED_OFF, AgentRunStatus.FAILED)
