"""Deterministic, idempotent SupportPilot AI demo-data seed (Phase 14, Part A).

    python manage.py seed_demo

Creates a small, coherent, fully-fictional demo world spanning every
domain the product actually implements, using the real domain service
layer wherever practical rather than hand-crafting rows — the same
services.py/orchestration.py functions the API views call. Every object is
identified by a stable, deterministic key (email, slug, external_id, or
name within a workspace) so running the command again finds and reuses the
same rows instead of duplicating them.

Never makes a live network/provider call: the LLM provider is the
repository's deterministic ``fake`` provider (the project default), the
knowledge embedding provider is the deterministic hash-based provider (the
only one that exists), and the commerce integration is
``DemoCommerceProvider`` — a real, production-shipped adapter that is
itself deterministic and network-free by design, not a test double.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from agents import orchestration
from agents import services as agent_services
from agents.models import (
    AgentDefinition,
    AgentRun,
    AgentRunStatus,
    AgentRunTrigger,
    AgentVersion,
    AgentVersionStatus,
)
from agents.providers.errors import ProviderInvalidRequestError
from agents.providers.fake import DeterministicFakeLLMProvider, FakeLLMScenario
from agents.providers.schemas import NormalizedHandoffRequest
from approvals import services as approval_services
from approvals.models import ApprovalDecisionValue, ApprovalRequest, ApprovalStatus
from channel_ingress import webchat as webchat_services
from channel_ingress.endpoint_admin import create_endpoint as create_channel_endpoint
from channel_ingress.models import ChannelEndpoint, ChannelType
from conversations import services as conversation_services
from conversations.models import Conversation, ConversationChannel, Message
from customers import services as customer_services
from customers.models import Customer
from evaluations import services as evaluation_services
from evaluations.models import EvaluationDataset, EvaluationRunStatus
from integrations import services as integration_services
from integrations.models import IntegrationConnection, IntegrationEnvironment, IntegrationProvider
from knowledge import services as knowledge_services
from knowledge.models import KnowledgeDocumentStatus, KnowledgeSource
from tickets import services as ticket_services
from tickets.models import HumanHandoffReason, Ticket, TicketStatus
from tools import services as tool_services
from tools.execution import execute_tool
from tools.models import ToolDefinition
from workspaces import services as workspace_services
from workspaces.models import Workspace, WorkspaceMembership, WorkspaceRole

#: A demo customer/user/workspace is always identified by one of these
#: deterministic markers so a second run finds and reuses it rather than
#: creating a duplicate (Section 4, 13). Never a random UUID.
DEMO_EMAIL_DOMAIN = "example.com"


def _demo_email(local_part: str) -> str:
    return f"{local_part}@{DEMO_EMAIL_DOMAIN}"


class Command(BaseCommand):
    help = "Seed a deterministic, idempotent SupportPilot AI demo dataset (no live provider call)."

    def handle(self, *args, **options):
        password = os.environ.get("SUPPORTPILOT_DEMO_PASSWORD")
        if not password:
            raise CommandError(
                "SUPPORTPILOT_DEMO_PASSWORD is not set. Refusing to seed demo users without an "
                "explicit password - set the environment variable and retry."
            )

        with transaction.atomic():
            summary = self._seed(password=password)

        self._report(summary)

    # ------------------------------------------------------------------
    # Small idempotent helpers
    # ------------------------------------------------------------------

    def _get_or_create_user(
        self, *, email: str, first_name: str, last_name: str, password: str
    ) -> User:
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "username": email,
                "first_name": first_name,
                "last_name": last_name,
                "is_active": True,
            },
        )
        if created:
            user.set_password(password)
            user.save(update_fields=["password"])
        return user

    def _get_or_create_workspace(self, *, name: str, owner: User) -> Workspace:
        from django.utils.text import slugify

        slug = slugify(name)
        existing = Workspace.objects.filter(slug=slug).first()
        if existing is not None:
            return existing
        return workspace_services.create_workspace(actor=owner, name=name)

    def _ensure_membership(
        self,
        *,
        workspace: Workspace,
        actor: User,
        actor_membership: WorkspaceMembership,
        user: User,
        role: str,
    ) -> WorkspaceMembership:
        existing = WorkspaceMembership.objects.filter(workspace=workspace, user=user).first()
        if existing is not None:
            return existing
        return workspace_services.add_workspace_member(
            workspace=workspace,
            actor=actor,
            actor_membership=actor_membership,
            email=user.email,
            role=role,
        )

    # ------------------------------------------------------------------
    # Top-level seed
    # ------------------------------------------------------------------

    def _seed(self, *, password: str) -> dict:
        summary: dict = {}

        # ---- Users -----------------------------------------------------
        owner1 = self._get_or_create_user(
            email=_demo_email("owner.acme"), first_name="Priya", last_name="Nair", password=password
        )
        admin1 = self._get_or_create_user(
            email=_demo_email("admin.acme"), first_name="Sam", last_name="Okafor", password=password
        )
        agent1 = self._get_or_create_user(
            email=_demo_email("agent.acme"),
            first_name="Lena",
            last_name="Fischer",
            password=password,
        )
        viewer1 = self._get_or_create_user(
            email=_demo_email("viewer.acme"),
            first_name="Tom",
            last_name="Bianchi",
            password=password,
        )
        owner2 = self._get_or_create_user(
            email=_demo_email("owner.nimbus"),
            first_name="Aiko",
            last_name="Tanaka",
            password=password,
        )

        # ---- Workspaces + memberships -----------------------------------
        ws1 = self._get_or_create_workspace(name="Acme Retail Support", owner=owner1)
        ws1_owner_membership = WorkspaceMembership.objects.get(workspace=ws1, user=owner1)
        self._ensure_membership(
            workspace=ws1,
            actor=owner1,
            actor_membership=ws1_owner_membership,
            user=admin1,
            role=WorkspaceRole.ADMIN,
        )
        self._ensure_membership(
            workspace=ws1,
            actor=owner1,
            actor_membership=ws1_owner_membership,
            user=agent1,
            role=WorkspaceRole.SUPPORT_AGENT,
        )
        self._ensure_membership(
            workspace=ws1,
            actor=owner1,
            actor_membership=ws1_owner_membership,
            user=viewer1,
            role=WorkspaceRole.VIEWER,
        )
        agent1_membership = WorkspaceMembership.objects.get(workspace=ws1, user=agent1)

        ws2 = self._get_or_create_workspace(name="Nimbus Cloud Support", owner=owner2)

        # ---- Customers (Section 5-6: identity fields double as the
        # "CustomerIdentity" the master prompt asks for — this model has no
        # separate identity table) --------------------------------------
        cust1 = self._get_or_create_customer(
            workspace=ws1,
            external_id="demo-cust-001",
            first_name="Jane",
            last_name="Rivera",
            email="jane.rivera@example.com",
        )
        cust2 = self._get_or_create_customer(
            workspace=ws1,
            external_id="demo-cust-002",
            first_name="Marco",
            last_name="Diaz",
            email="marco.diaz@example.com",
        )
        cust_ws2 = self._get_or_create_customer(
            workspace=ws2,
            external_id="demo-cust-101",
            first_name="Yuki",
            last_name="Sato",
            email="yuki.sato@example.com",
        )

        # ---- Knowledge -----------------------------------------------
        knowledge_summary = self._seed_knowledge(workspace=ws1, actor=owner1)

        # ---- Integrations ----------------------------------------------
        commerce_connection = self._seed_demo_commerce_connection(workspace=ws1, actor=owner1)
        stripe_connection = self._seed_stripe_connection(workspace=ws1, actor=owner1)
        calendar_connection = self._seed_calendar_connection(workspace=ws1, actor=owner1)

        # ---- Agent definition/version -----------------------------------
        agent_version = self._seed_agent(
            workspace=ws1,
            actor=owner1,
            commerce_connection=commerce_connection,
        )

        # ---- Channel endpoint + web-chat session + inbound event --------
        channel_summary = self._seed_channel(
            workspace=ws1,
            actor=owner1,
            agent_version=agent_version,
        )

        # ---- Conversations / messages / tickets / agent runs -----------
        conv_summary = self._seed_conversations(
            workspace=ws1,
            owner=owner1,
            owner_membership=ws1_owner_membership,
            agent_membership=agent1_membership,
            agent_version=agent_version,
            cust1=cust1,
            cust2=cust2,
            commerce_connection=commerce_connection,
            stripe_connection=stripe_connection,
            calendar_connection=calendar_connection,
        )

        # ---- Nimbus (second workspace): minimal, proves tenant isolation
        nimbus_conversation, _ = self._get_or_create_conversation(
            workspace=ws2,
            customer=cust_ws2,
            channel=ConversationChannel.EMAIL,
            subject="Question about my Nimbus subscription",
            external_id="demo-conv-ws2-001",
        )
        if not Message.objects.filter(workspace=ws2, external_id="demo-msg-ws2-001").exists():
            conversation_services.create_inbound_message(
                workspace=ws2,
                conversation=nimbus_conversation,
                body="Hi, can you confirm my subscription renewal date?",
                external_id="demo-msg-ws2-001",
            )

        # ---- Evaluations -------------------------------------------------
        eval_summary = self._seed_evaluations(
            workspace=ws1, actor=owner1, agent_version=agent_version
        )

        summary.update(
            {
                "workspaces": [ws1.name, ws2.name],
                "users": [owner1.email, admin1.email, agent1.email, viewer1.email, owner2.email],
                "customers": Customer.objects.filter(workspace__in=[ws1, ws2]).count(),
                "knowledge": knowledge_summary,
                "channel": channel_summary,
                "conversations": conv_summary,
                "evaluations": eval_summary,
                "integration_connections": IntegrationConnection.objects.filter(
                    workspace=ws1
                ).count(),
            }
        )
        return summary

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------

    def _get_or_create_customer(
        self, *, workspace: Workspace, external_id: str, first_name: str, last_name: str, email: str
    ) -> Customer:
        existing = Customer.objects.filter(workspace=workspace, external_id=external_id).first()
        if existing is not None:
            return existing
        return customer_services.create_customer(
            workspace=workspace,
            data={
                "external_id": external_id,
                "first_name": first_name,
                "last_name": last_name,
                "display_name": f"{first_name} {last_name}",
                "email": email,
            },
        )

    # ------------------------------------------------------------------
    # Knowledge
    # ------------------------------------------------------------------

    def _get_or_create_source(
        self, *, workspace: Workspace, actor: User, name: str, description: str
    ) -> KnowledgeSource:
        existing = KnowledgeSource.objects.filter(workspace=workspace, name=name).first()
        if existing is not None:
            return existing
        return knowledge_services.create_source(
            workspace=workspace, actor=actor, data={"name": name, "description": description}
        )

    def _seed_knowledge(self, *, workspace: Workspace, actor: User) -> dict:
        source = self._get_or_create_source(
            workspace=workspace,
            actor=actor,
            name="Support Policies",
            description="Shipping, refund, and appointment policies (demo content).",
        )
        documents = [
            (
                "Shipping Policy",
                "shipping-policy.txt",
                "Acme Retail ships all orders within two business days. Standard shipping "
                "takes five to seven business days; express shipping takes two to three "
                "business days. Customers receive a tracking link by email once an order "
                "ships. Orders cannot be redirected after they have shipped.",
            ),
            (
                "Refund Policy",
                "refund-policy.txt",
                "Acme Retail accepts returns within thirty days of delivery for a full refund "
                "to the original payment method. Refunds are processed within five business "
                "days of the returned item being received. Personalized or final-sale items "
                "are not eligible for a refund.",
            ),
        ]
        created_or_existing = []
        for title, filename, body in documents:
            document = source.documents.filter(title=title).first()
            if document is None:
                upload = SimpleUploadedFile(
                    filename, body.encode("utf-8"), content_type="text/plain"
                )
                document, job = knowledge_services.upload_document(
                    workspace=workspace,
                    source=source,
                    actor=actor,
                    title=title,
                    upload=upload,
                )
                # The real deterministic (hash-based, network-free) embedding
                # pipeline, run synchronously rather than waiting on a Celery
                # worker — see module docstring.
                knowledge_services.run_ingestion(job_id=job.id)
                document.refresh_from_db()
            created_or_existing.append(document)
        ready = sum(1 for d in created_or_existing if d.status == KnowledgeDocumentStatus.READY)
        return {"source": source.name, "documents": len(created_or_existing), "ready": ready}

    # ------------------------------------------------------------------
    # Integrations (Section 8: fake/sandbox values only, no live provider)
    # ------------------------------------------------------------------

    def _seed_demo_commerce_connection(
        self, *, workspace: Workspace, actor: User
    ) -> IntegrationConnection:
        existing = IntegrationConnection.objects.filter(
            workspace=workspace, provider=IntegrationProvider.DEMO_COMMERCE
        ).first()
        if existing is not None:
            return existing
        # DemoCommerceProvider (integrations.providers.demo_commerce) is a
        # real, production-shipped adapter that is itself deterministic and
        # network-free — its "credentials" are always empty by design.
        return integration_services.create_connection(
            workspace=workspace,
            actor=actor,
            provider=IntegrationProvider.DEMO_COMMERCE,
            display_name="Demo Commerce Catalog",
            environment=IntegrationEnvironment.TEST,
            credentials={},
            configuration={
                "orders": {
                    "ORD-1001": {
                        "status": "shipped",
                        "created_at": "2026-08-15T10:00:00Z",
                        "amount_minor": 4999,
                        "currency": "USD",
                    }
                }
            },
        )

    def _seed_stripe_connection(
        self, *, workspace: Workspace, actor: User
    ) -> IntegrationConnection:
        existing = IntegrationConnection.objects.filter(
            workspace=workspace, provider=IntegrationProvider.STRIPE
        ).first()
        if existing is not None:
            return existing
        # Clearly fictional sandbox-shaped value — never a real Stripe key.
        return integration_services.create_connection(
            workspace=workspace,
            actor=actor,
            provider=IntegrationProvider.STRIPE,
            display_name="Stripe (demo sandbox)",
            environment=IntegrationEnvironment.TEST,
            credentials={"secret_key": "sk_test_demo_0000000000000000"},
        )

    def _seed_calendar_connection(
        self, *, workspace: Workspace, actor: User
    ) -> IntegrationConnection:
        existing = IntegrationConnection.objects.filter(
            workspace=workspace, provider=IntegrationProvider.GOOGLE_CALENDAR
        ).first()
        if existing is not None:
            return existing
        return integration_services.create_connection(
            workspace=workspace,
            actor=actor,
            provider=IntegrationProvider.GOOGLE_CALENDAR,
            display_name="Google Calendar (demo sandbox)",
            environment=IntegrationEnvironment.TEST,
            credentials={"service_account_info": {"type": "service_account", "project_id": "demo"}},
        )

    # ------------------------------------------------------------------
    # Agent definition/version + tool bindings
    # ------------------------------------------------------------------

    def _seed_agent(
        self, *, workspace: Workspace, actor: User, commerce_connection: IntegrationConnection
    ) -> AgentVersion:
        # The code-owned tool registry is the source of truth; this
        # idempotently mirrors it into ToolDefinition (the same sync a data
        # migration performs) so the seed never depends on migration state
        # alone for a row it is about to bind.
        tool_services.sync_tool_definitions()

        definition = AgentDefinition.objects.filter(
            workspace=workspace, name="Support Copilot"
        ).first()
        if definition is None:
            definition = agent_services.create_agent_definition(
                workspace=workspace, actor=actor, data={"name": "Support Copilot"}
            )

        published = (
            AgentVersion.objects.filter(
                agent_definition=definition, status=AgentVersionStatus.PUBLISHED
            )
            .order_by("-version")
            .first()
        )
        if published is not None:
            return published

        version = agent_services.create_agent_version(
            workspace=workspace,
            agent_definition=definition,
            actor=actor,
            data={
                "provider": "fake",
                "model": "fake-support-model",
                "system_prompt": "You are Acme Retail's support copilot.",
                "max_model_calls": 3,
                "max_tool_calls": 3,
                "max_steps": 20,
            },
        )
        for key in ("order.lookup", "shipment.lookup", "payment.refund", "calendar.create_booking"):
            tool_definition = ToolDefinition.objects.get(key=key)
            tool_services.create_tool_binding(
                workspace=workspace,
                agent_version=version,
                actor=actor,
                tool_definition=tool_definition,
            )
        return agent_services.publish_agent_version(
            workspace=workspace, version=version, actor=actor
        )

    # ------------------------------------------------------------------
    # Channel endpoint + web-chat session + inbound event (Section 9)
    # ------------------------------------------------------------------

    def _seed_channel(
        self, *, workspace: Workspace, actor: User, agent_version: AgentVersion
    ) -> dict:
        endpoint = ChannelEndpoint.objects.filter(
            workspace=workspace, name="Website Chat Widget"
        ).first()
        if endpoint is None:
            endpoint, _plaintext_secret = create_channel_endpoint(
                workspace=workspace,
                actor=actor,
                channel=ChannelType.WEB_CHAT,
                name="Website Chat Widget",
                agent_version=agent_version,
            )
            # _plaintext_secret is None for web-chat by design (session
            # capability, not a signature) — nothing to guard here, but
            # never logged/printed regardless (Section 9, 17).

        # A session is normally short-lived/single-use by product design, so
        # there is no service-level "reuse" concept — but the seed still
        # keys off a stable, deterministic marker (the client_message_id
        # below, and this endpoint) so a second run reuses the demo's one
        # session/event rather than growing on every invocation.
        session = endpoint.chat_sessions.order_by("created_at").first()
        if session is None:
            session, _token = webchat_services.bootstrap_chat_session(endpoint=endpoint)
            # The plaintext session token is a one-time capability, never
            # persisted or logged beyond this call (Section 9) — the seed
            # does not print it.
            event = webchat_services.submit_chat_message(
                session=session,
                client_message_id="demo-webchat-msg-001",
                body="Hi, do you offer express shipping?",
            )
        else:
            event = endpoint.inbound_events.order_by("created_at").first()
        return {
            "endpoint": endpoint.name,
            "session_created": session.created_at is not None,
            "inbound_event_id": str(event.id),
        }

    # ------------------------------------------------------------------
    # Conversations / messages / tickets / agent runs / approvals / handoff
    # ------------------------------------------------------------------

    def _get_or_create_conversation(
        self,
        *,
        workspace: Workspace,
        customer: Customer,
        channel: str,
        subject: str,
        external_id: str,
    ) -> tuple[Conversation, bool]:
        existing = Conversation.objects.filter(workspace=workspace, external_id=external_id).first()
        if existing is not None:
            return existing, False
        conversation = conversation_services.create_conversation(
            workspace=workspace,
            customer=customer,
            channel=channel,
            subject=subject,
            external_id=external_id,
        )
        return conversation, True

    def _seed_conversations(
        self,
        *,
        workspace: Workspace,
        owner: User,
        owner_membership: WorkspaceMembership,
        agent_membership: WorkspaceMembership,
        agent_version: AgentVersion,
        cust1: Customer,
        cust2: Customer,
        commerce_connection: IntegrationConnection,
        stripe_connection: IntegrationConnection,
        calendar_connection: IntegrationConnection,
    ) -> dict:
        # --- Conversation A: active, successful agent run ------------------
        conv_a, created_a = self._get_or_create_conversation(
            workspace=workspace,
            customer=cust1,
            channel=ConversationChannel.WEB,
            subject="Order status question",
            external_id="demo-conv-001",
        )
        if created_a:
            trigger_message = conversation_services.create_inbound_message(
                workspace=workspace,
                conversation=conv_a,
                body="Hi, can you check the status of order ORD-1001?",
                external_id="demo-msg-001",
            )
            self._run_scripted_conversation_agent(
                workspace=workspace,
                conversation=conv_a,
                trigger_message=trigger_message,
                agent_version=agent_version,
                scenario=FakeLLMScenario(response="Order ORD-1001 has shipped and is on its way!"),
            )

        # --- Conversation B: resolved -----------------------------------
        conv_b, created_b = self._get_or_create_conversation(
            workspace=workspace,
            customer=cust2,
            channel=ConversationChannel.EMAIL,
            subject="Return request",
            external_id="demo-conv-002",
        )
        if created_b:
            conversation_services.create_inbound_message(
                workspace=workspace,
                conversation=conv_b,
                body="I'd like to return an item I ordered.",
                external_id="demo-msg-002",
            )
            conversation_services.create_outbound_message(
                workspace=workspace,
                actor_membership=agent_membership,
                conversation=conv_b,
                body="Your return has been processed and the refund is on its way.",
                external_id="demo-msg-003",
            )
            conversation_services.close_conversation(
                workspace=workspace,
                actor=owner,
                actor_membership=owner_membership,
                conversation=conv_b,
            )
        ticket_open = self._get_or_create_ticket(
            workspace=workspace,
            customer=cust1,
            conversation=conv_a,
            subject="Follow up: express shipping availability",
            external_id="demo-ticket-001",
        )
        ticket_resolved = self._get_or_create_ticket(
            workspace=workspace,
            customer=cust2,
            conversation=conv_b,
            subject="Return processed",
            external_id="demo-ticket-002",
        )
        if ticket_resolved.status != TicketStatus.RESOLVED:
            ticket_services.resolve_ticket(
                workspace=workspace,
                actor=owner,
                actor_membership=owner_membership,
                ticket=ticket_resolved,
            )

        # --- Conversation C: a real refund tool call, pending approval, and
        # a second, already-decided one (Section 11) --------------------
        conv_c, created_c = self._get_or_create_conversation(
            workspace=workspace,
            customer=cust1,
            channel=ConversationChannel.WEB,
            subject="Refund request — order over threshold",
            external_id="demo-conv-003",
        )
        pending_approval, decided_approval = self._seed_refund_approvals(
            workspace=workspace,
            owner=owner,
            conversation=conv_c,
            agent_version=agent_version,
        )

        # --- Conversation D: human handoff ------------------------------
        conv_d, created_d = self._get_or_create_conversation(
            workspace=workspace,
            customer=cust2,
            channel=ConversationChannel.WEB,
            subject="Wants to speak to a person",
            external_id="demo-conv-004",
        )
        if created_d:
            trigger_message = conversation_services.create_inbound_message(
                workspace=workspace,
                conversation=conv_d,
                body="This isn't working, I want to talk to a real person.",
                external_id="demo-msg-004",
            )
            self._run_scripted_conversation_agent(
                workspace=workspace,
                conversation=conv_d,
                trigger_message=trigger_message,
                agent_version=agent_version,
                scenario=FakeLLMScenario(
                    response="",
                    handoff_request=NormalizedHandoffRequest(
                        reason_code=HumanHandoffReason.CUSTOMER_REQUESTED,
                        summary="Customer explicitly asked for a human agent.",
                    ),
                ),
            )
        # Fetched by conversation, not by the run just above, so this is
        # correct on both the first run and every idempotent reuse.
        handoff = conv_d.human_handoffs.first()

        # --- Conversation E: a real, safe tool failure (order not found) --
        conv_e, created_e = self._get_or_create_conversation(
            workspace=workspace,
            customer=cust1,
            channel=ConversationChannel.WEB,
            subject="Order status — not found",
            external_id="demo-conv-005",
        )
        if created_e:
            trigger_message = conversation_services.create_inbound_message(
                workspace=workspace,
                conversation=conv_e,
                body="What's the status of order ORD-9999?",
                external_id="demo-msg-005",
            )
            self._run_scripted_conversation_agent(
                workspace=workspace,
                conversation=conv_e,
                trigger_message=trigger_message,
                agent_version=agent_version,
                scenario=FakeLLMScenario(
                    error=ProviderInvalidRequestError, error_message="demo: order lookup failed"
                ),
            )

        return {
            "total": Conversation.objects.filter(workspace=workspace).count(),
            "conversation_a_status": conv_a.status,
            "conversation_b_status": conv_b.status,
            "conversation_c_status": conv_c.status,
            "conversation_d_status": conv_d.status,
            "tickets": {ticket_open.status, ticket_resolved.status},
            "pending_approval": str(pending_approval.id),
            "decided_approval": str(decided_approval.id),
            "handoff": str(handoff.id) if handoff else None,
        }

    def _get_or_create_ticket(
        self,
        *,
        workspace: Workspace,
        customer: Customer,
        conversation: Conversation,
        subject: str,
        external_id: str,
    ) -> Ticket:
        existing = Ticket.objects.filter(
            workspace=workspace, metadata__external_id=external_id
        ).first()
        if existing is not None:
            return existing
        return ticket_services.create_ticket(
            workspace=workspace,
            customer=customer,
            subject=subject,
            conversation=conversation,
            metadata={"external_id": external_id},
        )

    def _run_scripted_conversation_agent(
        self,
        *,
        workspace: Workspace,
        conversation: Conversation,
        trigger_message,
        agent_version: AgentVersion,
        scenario: FakeLLMScenario,
    ) -> AgentRun:
        """Start and fully execute a real, conversation-linked agent run
        against a scripted deterministic response — the same
        ``orchestration`` entry points the API views call. The LLM
        provider substitution below only varies *which* canned, offline
        response the run receives; it never reaches a network."""
        run = orchestration.start_support_agent_run(
            workspace=workspace,
            actor=None,
            conversation=conversation,
            trigger_message=trigger_message,
            agent_version=agent_version,
        )
        if run.status != AgentRunStatus.PENDING:
            return run  # already executed by an earlier seed run
        provider = DeterministicFakeLLMProvider(scenario)
        with mock.patch.object(agent_services, "get_llm_provider", lambda: provider):
            orchestration.execute_support_agent_run(run.id)
        run.refresh_from_db()
        return run

    def _seed_refund_approvals(
        self,
        *,
        workspace: Workspace,
        owner: User,
        conversation: Conversation,
        agent_version: AgentVersion,
    ) -> tuple[ApprovalRequest, ApprovalRequest]:
        existing_pending = ApprovalRequest.objects.filter(
            workspace=workspace,
            status=ApprovalStatus.PENDING,
            tool_execution__agent_run__conversation=conversation,
        ).first()
        existing_decided = ApprovalRequest.objects.filter(
            workspace=workspace,
            status=ApprovalStatus.APPROVED,
            decision__safe_comment="demo: approved by owner",
        ).first()
        if existing_pending is not None and existing_decided is not None:
            return existing_pending, existing_decided

        from integrations.providers.base import NormalizedPayment
        from integrations.providers.fakes import FakePaymentProvider

        fake_payment = FakePaymentProvider(
            payments={
                "pi_demo_1": NormalizedPayment(
                    payment_id="pi_demo_1",
                    external_payment_id="pi_demo_1",
                    status="succeeded",
                    amount_minor=100000,
                    currency="USD",
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                    refunded_amount_minor=0,
                ),
                "pi_demo_2": NormalizedPayment(
                    payment_id="pi_demo_2",
                    external_payment_id="pi_demo_2",
                    status="succeeded",
                    amount_minor=100000,
                    currency="USD",
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                    refunded_amount_minor=0,
                ),
            }
        )

        def _run_refund(*, run: AgentRun, payment_reference: str) -> None:
            from tools.errors import ToolError

            with mock.patch(
                "integrations.services.get_payment_provider", lambda provider: fake_payment
            ):
                try:
                    execute_tool(
                        agent_run=run,
                        tool_key="payment.refund",
                        arguments={
                            "payment_reference": payment_reference,
                            "amount_minor": 15000,
                            "currency": "usd",
                        },
                    )
                except ToolError:
                    pass  # expected: approval_required

        if existing_pending is None:
            run1 = agent_services.create_agent_run(
                workspace=workspace,
                agent_version=agent_version,
                actor=None,
                input_message="Please refund my order, it arrived damaged.",
                trigger=AgentRunTrigger.CONVERSATION,
                conversation=conversation,
            )
            run1.status = AgentRunStatus.RUNNING
            run1.started_at = timezone.now()
            run1.save(update_fields=["status", "started_at", "updated_at"])
            _run_refund(run=run1, payment_reference="pi_demo_1")
            existing_pending = ApprovalRequest.objects.get(tool_execution__agent_run=run1)

        if existing_decided is None:
            run2 = agent_services.create_agent_run(
                workspace=workspace,
                agent_version=agent_version,
                actor=None,
                input_message="Please refund my second order too.",
                trigger=AgentRunTrigger.MANUAL,
            )
            run2.status = AgentRunStatus.RUNNING
            run2.started_at = timezone.now()
            run2.save(update_fields=["status", "started_at", "updated_at"])
            _run_refund(run=run2, payment_reference="pi_demo_2")
            to_decide = ApprovalRequest.objects.get(tool_execution__agent_run=run2)
            existing_decided = approval_services.decide_approval(
                workspace=workspace,
                approval_request=to_decide,
                actor=owner,
                actor_role=WorkspaceRole.OWNER,
                decision=ApprovalDecisionValue.APPROVE,
                comment="demo: approved by owner",
            )

        return existing_pending, existing_decided

    # ------------------------------------------------------------------
    # Evaluations (Section 10)
    # ------------------------------------------------------------------

    def _seed_evaluations(
        self, *, workspace: Workspace, actor: User, agent_version: AgentVersion
    ) -> dict:
        dataset = EvaluationDataset.objects.filter(
            workspace=workspace, name="Support Regression Suite"
        ).first()
        if dataset is None:
            dataset = evaluation_services.create_evaluation_dataset(
                workspace=workspace,
                actor=actor,
                data={
                    "name": "Support Regression Suite",
                    "description": "Deterministic demo evaluation cases.",
                },
            )
        if not dataset.cases.filter(key="order-status-basic").exists():
            evaluation_services.create_evaluation_case(
                workspace=workspace,
                dataset=dataset,
                actor=actor,
                data={
                    "key": "order-status-basic",
                    "name": "Answers a plain order-status question",
                    "input_message": "What's the status of my order?",
                    "expectations": {},  # no assertions -> trivially passes
                },
            )
        if not dataset.cases.filter(key="order-status-requires-lookup").exists():
            evaluation_services.create_evaluation_case(
                workspace=workspace,
                dataset=dataset,
                actor=actor,
                data={
                    "key": "order-status-requires-lookup",
                    "name": "Must call order.lookup before answering (regression case)",
                    "input_message": "Check my order please.",
                    # The default scripted response below never calls a
                    # tool, so this deterministically fails — a real,
                    # representative regression case, not a fabricated one.
                    "expectations": {"required_tool_sequence": ["order.lookup"]},
                },
            )

        from evaluations.models import EvaluationRun

        existing_run = EvaluationRun.objects.filter(
            workspace=workspace,
            dataset=dataset,
            status__in=[EvaluationRunStatus.SUCCEEDED, EvaluationRunStatus.PARTIAL],
        ).first()
        if existing_run is not None:
            return {
                "dataset": dataset.name,
                "cases": dataset.cases.count(),
                "run": str(existing_run.id),
                "run_status": existing_run.status,
            }

        provider = DeterministicFakeLLMProvider(
            FakeLLMScenario(response="Your order is on its way.")
        )
        with mock.patch.object(agent_services, "get_llm_provider", lambda: provider):
            run = evaluation_services.start_evaluation_run(
                workspace=workspace,
                actor=actor,
                dataset=dataset,
                agent_version=agent_version,
            )
            evaluation_services.claim_evaluation_run(run.id)
            for result in run.results.all():
                # Auto-finalizes the run as soon as the last (non-replay)
                # case completes (evaluations.services._record_case_completion)
                # — no separate finalize call needed/safe to duplicate here.
                evaluation_services.execute_evaluation_case(result.id)
            run.refresh_from_db()

        return {
            "dataset": dataset.name,
            "cases": dataset.cases.count(),
            "run": str(run.id) if run else None,
            "run_status": run.status if run else None,
        }

    # ------------------------------------------------------------------
    # Output (Section 17: counts/identifiers only — never a secret)
    # ------------------------------------------------------------------

    def _report(self, summary: dict) -> None:
        self.stdout.write(self.style.SUCCESS("SupportPilot AI demo seed complete."))
        self.stdout.write(f"  Workspaces: {', '.join(summary['workspaces'])}")
        self.stdout.write(f"  Demo users ({len(summary['users'])}): {', '.join(summary['users'])}")
        self.stdout.write(f"  Customers: {summary['customers']}")
        self.stdout.write(
            f"  Knowledge: source={summary['knowledge']['source']!r}, "
            f"documents={summary['knowledge']['documents']} (ready={summary['knowledge']['ready']})"
        )
        self.stdout.write(f"  Integration connections: {summary['integration_connections']}")
        self.stdout.write(
            f"  Channel endpoint: {summary['channel']['endpoint']!r}, "
            f"inbound event={summary['channel']['inbound_event_id']}"
        )
        conv = summary["conversations"]
        self.stdout.write(
            f"  Conversations: {conv['total']} total "
            f"(A={conv['conversation_a_status']}, B={conv['conversation_b_status']}, "
            f"C={conv['conversation_c_status']}, D={conv['conversation_d_status']})"
        )
        self.stdout.write(f"  Tickets: {conv['tickets']}")
        self.stdout.write(
            f"  Approvals: pending={conv['pending_approval']}, decided={conv['decided_approval']}"
        )
        self.stdout.write(f"  Handoff: {conv['handoff']}")
        ev = summary["evaluations"]
        self.stdout.write(
            f"  Evaluation dataset {ev['dataset']!r}: {ev['cases']} cases, "
            f"run={ev['run']} (status={ev['run_status']})"
        )
