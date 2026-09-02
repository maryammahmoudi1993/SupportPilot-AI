"""Phase 14 (Section 18): `manage.py seed_demo` idempotency and safety
regression tests.

The command never makes a live network/provider call — the LLM provider
is the deterministic ``fake`` provider, the embedding provider is the
deterministic hash-based provider, and the commerce integration
(``demo_commerce``) is a real, production-shipped, network-free adapter —
so these tests run entirely offline against the real ORM, no mocking of
the seed command itself required.
"""

from __future__ import annotations

import io

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.models import User
from agents.models import AgentDefinition, AgentRun, AgentVersion
from approvals.models import ApprovalDecision, ApprovalRequest
from channel_ingress.models import ChannelEndpoint, ChatSession, InboundChannelEvent
from conversations.models import Conversation, Message
from customers.models import Customer
from evaluations.models import EvaluationCase, EvaluationDataset, EvaluationResult, EvaluationRun
from integrations.models import IntegrationConnection
from knowledge.models import KnowledgeDocument, KnowledgeSource
from tickets.models import HumanHandoff, Ticket
from tools.models import ToolBinding, ToolExecution
from workspaces.models import Workspace, WorkspaceMembership

DEMO_PASSWORD = "demo-seed-test-password-not-real"

_MODELS = [
    Workspace,
    WorkspaceMembership,
    User,
    Customer,
    Conversation,
    Message,
    Ticket,
    HumanHandoff,
    KnowledgeSource,
    KnowledgeDocument,
    AgentDefinition,
    AgentVersion,
    AgentRun,
    ToolBinding,
    ToolExecution,
    ApprovalRequest,
    ApprovalDecision,
    EvaluationDataset,
    EvaluationCase,
    EvaluationRun,
    EvaluationResult,
    IntegrationConnection,
    ChannelEndpoint,
    ChatSession,
    InboundChannelEvent,
]


def _run_seed(monkeypatch, *, password: str | None = DEMO_PASSWORD) -> str:
    if password is None:
        monkeypatch.delenv("SUPPORTPILOT_DEMO_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("SUPPORTPILOT_DEMO_PASSWORD", password)
    out = io.StringIO()
    call_command("seed_demo", stdout=out)
    return out.getvalue()


@pytest.mark.django_db
class TestSeedDemoIdempotency:
    def test_first_run_succeeds(self, monkeypatch):
        output = _run_seed(monkeypatch)
        assert "SupportPilot AI demo seed complete." in output
        assert Workspace.objects.count() == 2
        assert User.objects.count() == 5

    def test_second_run_is_idempotent(self, monkeypatch):
        _run_seed(monkeypatch)
        counts_after_first = {model: model.objects.count() for model in _MODELS}
        ids_after_first = {
            "approvals": set(ApprovalRequest.objects.values_list("id", flat=True)),
            "evaluation_run": set(EvaluationRun.objects.values_list("id", flat=True)),
            "handoff": set(HumanHandoff.objects.values_list("id", flat=True)),
            "workspaces": set(Workspace.objects.values_list("id", flat=True)),
            "users": set(User.objects.values_list("id", flat=True)),
        }

        _run_seed(monkeypatch)

        for model in _MODELS:
            assert model.objects.count() == counts_after_first[model], (
                f"{model.__name__} count changed on second run: "
                f"{counts_after_first[model]} -> {model.objects.count()}"
            )
        assert (
            set(ApprovalRequest.objects.values_list("id", flat=True))
            == ids_after_first["approvals"]
        )
        assert (
            set(EvaluationRun.objects.values_list("id", flat=True))
            == ids_after_first["evaluation_run"]
        )
        assert set(HumanHandoff.objects.values_list("id", flat=True)) == ids_after_first["handoff"]
        assert set(Workspace.objects.values_list("id", flat=True)) == ids_after_first["workspaces"]
        assert set(User.objects.values_list("id", flat=True)) == ids_after_first["users"]

    def test_relationships_are_correct(self, monkeypatch):
        _run_seed(monkeypatch)

        acme = Workspace.objects.get(slug="acme-retail-support")
        nimbus = Workspace.objects.get(slug="nimbus-cloud-support")

        # Every membership/customer/conversation/etc. created for Acme stays
        # scoped to Acme; Nimbus is untouched by Acme's rich demo story.
        assert WorkspaceMembership.objects.filter(workspace=acme).count() == 4
        assert WorkspaceMembership.objects.filter(workspace=nimbus).count() == 1
        assert Conversation.objects.filter(workspace=acme).count() == 5
        assert Conversation.objects.filter(workspace=nimbus).count() == 1

        evaluation_run = EvaluationRun.objects.get(workspace=acme)
        assert evaluation_run.status == "succeeded"
        assert evaluation_run.results.count() == 2
        assert evaluation_run.results.filter(passed=True).count() == 1
        assert evaluation_run.results.filter(passed=False).count() == 1

        pending = ApprovalRequest.objects.filter(workspace=acme, status="pending").first()
        decided = ApprovalRequest.objects.filter(workspace=acme, status="approved").first()
        assert pending is not None
        assert decided is not None
        assert decided.decision.decision == "approve"

    def test_cross_workspace_data_is_isolated(self, monkeypatch):
        _run_seed(monkeypatch)

        acme = Workspace.objects.get(slug="acme-retail-support")
        nimbus = Workspace.objects.get(slug="nimbus-cloud-support")

        nimbus_customers = set(
            Customer.objects.filter(workspace=nimbus).values_list("id", flat=True)
        )
        acme_customers = set(Customer.objects.filter(workspace=acme).values_list("id", flat=True))
        assert nimbus_customers.isdisjoint(acme_customers)

        # No Acme-owned object (conversation, agent run, evaluation, ...)
        # references the Nimbus workspace or vice versa.
        assert not Conversation.objects.filter(
            workspace=nimbus, customer__in=acme_customers
        ).exists()
        assert AgentDefinition.objects.filter(workspace=nimbus).count() == 0
        assert EvaluationDataset.objects.filter(workspace=nimbus).count() == 0


@pytest.mark.django_db
class TestSeedDemoSafety:
    def test_missing_password_fails_clearly_without_seeding(self, monkeypatch):
        with pytest.raises(CommandError, match="SUPPORTPILOT_DEMO_PASSWORD"):
            _run_seed(monkeypatch, password=None)
        assert Workspace.objects.count() == 0
        assert User.objects.count() == 0

    def test_password_never_printed(self, monkeypatch):
        output = _run_seed(monkeypatch, password="a-very-distinctive-demo-password-marker")
        assert "a-very-distinctive-demo-password-marker" not in output

    def test_fake_credentials_never_printed(self, monkeypatch):
        output = _run_seed(monkeypatch)
        assert "sk_test_demo" not in output
        assert "service_account" not in output

    def test_no_password_hash_or_secret_field_name_in_output(self, monkeypatch):
        output = _run_seed(monkeypatch)
        for forbidden in ("password", "secret", "credential", "encrypted"):
            assert forbidden not in output.lower()

    def test_deliberate_failure_rolls_back_everything(self, monkeypatch):
        # A late-stage failure (evaluation seeding) must not leave a
        # half-created demo world behind — the whole command runs inside
        # one top-level transaction (Section 16).
        monkeypatch.setenv("SUPPORTPILOT_DEMO_PASSWORD", DEMO_PASSWORD)

        def _boom(self, *, workspace, actor, agent_version):
            raise RuntimeError("deliberate failure for the rollback test")

        monkeypatch.setattr("common.management.commands.seed_demo.Command._seed_evaluations", _boom)
        with pytest.raises(RuntimeError, match="deliberate failure"):
            call_command("seed_demo")

        assert Workspace.objects.count() == 0
        assert User.objects.count() == 0
        assert Customer.objects.count() == 0
        assert Conversation.objects.count() == 0
