/**
 * Creates synthetic backend data for the E2E suite: one user with two real
 * workspace memberships (owner + support_agent) and one user with zero
 * memberships. Shells out to the real Django backend (`manage.py shell`) —
 * no mocks, no fixtures baked into the frontend — so the suite exercises
 * the actual `/auth/login/`, `/auth/me/`, and workspace-scoped contract.
 *
 * Output (`.e2e-data.json`, gitignored) is read by tests and by
 * `global-teardown.ts`. Cleaned up unconditionally in teardown; also wipes
 * any leftover `e2e-*`/`E2E *` data from a prior aborted run before
 * creating fresh records, so a crashed run never leaves stale rows that
 * silently corrupt the next one.
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const BACKEND_ROOT = path.resolve(__dirname, "..", "..", "backend");
const PYTHON = path.join(BACKEND_ROOT, "venv", "Scripts", "python.exe");
export const DATA_FILE = path.resolve(__dirname, ".e2e-data.json");

const SETUP_SCRIPT = `
import json
from datetime import timedelta
from django.utils import timezone
from accounts.models import User
from agents.models import AgentDefinition, AgentProvider, AgentRun, AgentRunStatus, AgentRunTrigger, AgentStep, AgentStepStatus, AgentStepType, AgentVersion, AgentVersionStatus
from approvals.models import ApprovalDecision, ApprovalDecisionValue, ApprovalRequest, ApprovalStatus
from common.redaction import redact
from conversations.models import Conversation, ConversationChannel, ConversationStatus, Message, MessageDirection, MessageSenderType
from customers.models import Customer
from policies.models import PolicyEffect, PolicyEvaluation, RiskAssessment
from knowledge.models import KnowledgeDocument, KnowledgeDocumentStatus, KnowledgeIngestionJob, KnowledgeIngestionStatus, KnowledgeSource, KnowledgeSourceType
from tickets.models import HumanHandoff, HumanHandoffReason, HumanHandoffStatus, Ticket, TicketPriority, TicketStatus
from tools.contracts import RiskLevel, SideEffectType
from tools.models import ToolBinding, ToolDefinition, ToolExecution, ToolExecutionStatus
from tools.services import sync_tool_definitions
from workspaces.models import Workspace, WorkspaceMembership, WorkspaceRole

PASSWORD = "e2e-Test-Passw0rd!"

def make_user(username, email, first, last):
    u = User(username=username, email=email, first_name=first, last_name=last, is_active=True)
    u.set_password(PASSWORD)
    u.save()
    return u

User.objects.filter(email__startswith="e2e-").delete()
# See global-teardown.ts for why ApprovalRequest/ToolExecution/AgentRun
# (on_delete=PROTECT chains through ToolBinding/AgentVersion/RiskAssessment)
# must be cleared before a Workspace cascade delete, and in that order.
# HumanHandoff has no PROTECT relations (workspace CASCADE, agent_run/ticket
# SET_NULL) so it needs no special ordering.
ApprovalRequest.objects.filter(workspace__name__startswith="E2E ").delete()
ToolExecution.objects.filter(workspace__name__startswith="E2E ").delete()
AgentRun.objects.filter(workspace__name__startswith="E2E ").delete()
Workspace.objects.filter(name__startswith="E2E ").delete()

primary = make_user("e2e-primary", "e2e-primary@example.com", "E2E", "Primary")
zero = make_user("e2e-zero", "e2e-zero@example.com", "E2E", "ZeroWorkspace")

ws_a = Workspace.objects.create(name="E2E Workspace A")
ws_b = Workspace.objects.create(name="E2E Workspace B")
membership_a = WorkspaceMembership.objects.create(workspace=ws_a, user=primary, role=WorkspaceRole.OWNER)
membership_b = WorkspaceMembership.objects.create(
    workspace=ws_b, user=primary, role=WorkspaceRole.SUPPORT_AGENT
)

# Customers domain (Phase 19 Chunk 1) — real cross-workspace data so the
# real-backend smoke and later Phase 19 E2E specs can prove tenant
# isolation, search, and pagination against the actual API, not a mock.
# Customer rows cascade-delete with their workspace (Customer.workspace,
# on_delete=CASCADE) so no separate cleanup is needed here.
ws_a_customer = Customer.objects.create(
    workspace=ws_a, first_name="Ada", last_name="Lovelace",
    email="ada.lovelace@example.com", company="Analytical Engines Ltd", is_active=True,
)
Customer.objects.create(
    workspace=ws_a, first_name="Grace", last_name="Hopper",
    email="grace.hopper@example.com", company="COBOL Systems", is_active=True,
)
Customer.objects.create(
    workspace=ws_a, first_name="Retired", last_name="Account",
    email="retired.account@example.com", company="Formerly Inc", is_active=False,
)
ws_b_customer = Customer.objects.create(
    workspace=ws_b, first_name="Bob", last_name="Belcher",
    email="bob.belcher@example.com", company="Globex Burgers", is_active=True,
    # Real notes content so Customer detail's notes section (a real, if
    # optional, rendered field) is actually exercised by the E2E accessibility
    # scan rather than skipped by an empty fixture (Phase 19 Chunk 4 found the
    # <dt>/<dd> markup here wasn't wrapped in a <dl> precisely because no
    # existing fixture ever populated this field).
    notes="Prefers email contact. VIP account since 2024.",
)

# Conversations/messages domain (Phase 19 Chunk 2) — real cross-workspace
# data so the real-backend smoke and later Phase 19 E2E specs can prove
# tenant isolation, filters, message ordering, and sender/source rendering
# against the actual API. Conversation/Message rows cascade-delete with
# their workspace (both FK workspace, on_delete=CASCADE).
ws_b_conversation = Conversation.objects.create(
    workspace=ws_b, customer=ws_b_customer, channel=ConversationChannel.WEB,
    status=ConversationStatus.OPEN, subject="Order delayed", assigned_to=membership_b,
)
Message.objects.create(
    workspace=ws_b, conversation=ws_b_conversation, sender_type=MessageSenderType.CUSTOMER,
    direction=MessageDirection.INBOUND, body="My order hasn't arrived yet.",
)
Message.objects.create(
    workspace=ws_b, conversation=ws_b_conversation, sender_type=MessageSenderType.HUMAN_AGENT,
    sender_membership=membership_b, direction=MessageDirection.OUTBOUND,
    body="Let me look into that for you right away.",
)
Message.objects.create(
    workspace=ws_b, conversation=ws_b_conversation, sender_type=MessageSenderType.AI_AGENT,
    direction=MessageDirection.OUTBOUND, body="Tracking shows the package is out for delivery today.",
)
Message.objects.create(
    workspace=ws_b, conversation=ws_b_conversation, sender_type=MessageSenderType.SYSTEM,
    direction=MessageDirection.INTERNAL, body="Escalation timer paused: carrier confirmed transit.",
)
# Phase 19 Chunk 4 content-safety fixture: HTML/script-looking real message
# content, to prove end to end (not just via unit test) that it is rendered
# as inert plain text, never interpreted as markup.
Message.objects.create(
    workspace=ws_b, conversation=ws_b_conversation, sender_type=MessageSenderType.CUSTOMER,
    direction=MessageDirection.INBOUND,
    body="<b>Is this bold?</b> <script>window.__xss_marker = true;</script>",
)
ws_b_conversation.last_message_at = Message.objects.filter(conversation=ws_b_conversation).latest(
    "created_at"
).created_at
ws_b_conversation.save(update_fields=["last_message_at"])

ws_b_unassigned_conversation = Conversation.objects.create(
    workspace=ws_b, customer=ws_b_customer, channel=ConversationChannel.CHAT,
    status=ConversationStatus.CLOSED, subject="Unassigned chat inquiry",
)

ws_a_conversation = Conversation.objects.create(
    workspace=ws_a, customer=ws_a_customer, channel=ConversationChannel.EMAIL,
    status=ConversationStatus.PENDING, subject="Billing question", assigned_to=membership_a,
)
Message.objects.create(
    workspace=ws_a, conversation=ws_a_conversation, sender_type=MessageSenderType.CUSTOMER,
    direction=MessageDirection.INBOUND, body="Can you clarify this month's invoice?",
)

# Tickets domain (Phase 19 Chunk 3) — real cross-workspace data, with a real
# ticket/conversation relationship on one Workspace B ticket, so the
# real-backend smoke and E2E specs can prove tenant isolation, filters, and
# cross-domain navigation (Ticket -> Customer, Ticket -> Conversation,
# Customer -> related Tickets/Conversations) against the actual API. Ticket
# rows cascade-delete with their workspace (Ticket.workspace, on_delete=CASCADE).
ws_b_ticket = Ticket.objects.create(
    workspace=ws_b, customer=ws_b_customer, conversation=ws_b_conversation,
    subject="Refund for delayed order", description="Customer requests a refund.",
    priority=TicketPriority.URGENT, assigned_to=membership_b,
)
ws_b_resolved_ticket = Ticket.objects.create(
    workspace=ws_b, customer=ws_b_customer, subject="Resolved billing question",
    status=TicketStatus.RESOLVED, priority=TicketPriority.LOW,
)
ws_a_ticket = Ticket.objects.create(
    workspace=ws_a, customer=ws_a_customer, subject="Workspace A only ticket",
    priority=TicketPriority.NORMAL,
)

# Phase 19 Chunk 4A: a second real page of Workspace B tickets, so the
# keyboard-only journey can prove real pagination (Next/Previous) rather
# than asserting it only via a mocked page in a unit test. Low priority so
# ws_b_ticket (urgent) always sorts first, on page 1, keeping every existing
# spec's assumptions about what's visible on page 1 unaffected.
Ticket.objects.bulk_create([
    Ticket(
        workspace=ws_b, customer=ws_b_customer, subject=f"Bulk ticket {i}",
        priority=TicketPriority.LOW,
    )
    for i in range(55)
])

# Agent Runs domain (Phase 20 Chunk 1) — real cross-workspace AgentDefinition
# / AgentVersion / AgentRun / AgentStep rows, created directly (not via the
# orchestration service — that would make real, billed provider calls) so the
# real-backend smoke can prove tenant isolation, status/lifecycle rendering,
# real Run -> Conversation/Ticket cross-links, and non-terminal-run polling
# against the actual API. Rows cascade/PROTECT per agents/models.py; deleted
# by AgentDefinition.workspace CASCADE except AgentVersion (PROTECT from
# AgentRun) — cleaned up in dependency order in global-teardown.ts.
ws_b_agent_def = AgentDefinition.objects.create(workspace=ws_b, name="E2E Support Agent")
ws_b_agent_version = AgentVersion.objects.create(
    agent_definition=ws_b_agent_def, version=1, status=AgentVersionStatus.PUBLISHED,
    provider=AgentProvider.FAKE, model="fake-v1", published_at=timezone.now(),
)
ws_b_agent_run_succeeded = AgentRun.objects.create(
    workspace=ws_b, agent_version=ws_b_agent_version, conversation=ws_b_conversation,
    ticket=ws_b_ticket, trigger=AgentRunTrigger.CONVERSATION, status=AgentRunStatus.SUCCEEDED,
    input_message="My order hasn't arrived yet.",
    final_response="Your refund has been processed.",
    started_at=timezone.now(), completed_at=timezone.now(),
    model_call_count=1, step_count=2, tool_call_count=0,
    input_tokens=120, output_tokens=64, total_tokens=184,
)
AgentStep.objects.bulk_create([
    AgentStep(
        run=ws_b_agent_run_succeeded, workspace=ws_b, sequence=1,
        step_type=AgentStepType.RUN_STARTED, status=AgentStepStatus.SUCCEEDED,
    ),
    AgentStep(
        run=ws_b_agent_run_succeeded, workspace=ws_b, sequence=2,
        step_type=AgentStepType.RUN_COMPLETED, status=AgentStepStatus.SUCCEEDED,
        provider="fake", model="fake-v1", latency_ms=42,
    ),
])
# Non-terminal (running) — real-backend smoke proves it renders correctly and
# is the one status eligible for the frontend's polling behavior.
ws_b_agent_run_running = AgentRun.objects.create(
    workspace=ws_b, agent_version=ws_b_agent_version, trigger=AgentRunTrigger.MANUAL,
    status=AgentRunStatus.RUNNING, input_message="Looking up account status.",
    started_at=timezone.now(),
)
ws_a_agent_def = AgentDefinition.objects.create(workspace=ws_a, name="E2E Workspace A Agent")
ws_a_agent_version = AgentVersion.objects.create(
    agent_definition=ws_a_agent_def, version=1, status=AgentVersionStatus.PUBLISHED,
    provider=AgentProvider.FAKE, model="fake-v1", published_at=timezone.now(),
)
ws_a_agent_run = AgentRun.objects.create(
    workspace=ws_a, agent_version=ws_a_agent_version, trigger=AgentRunTrigger.MANUAL,
    status=AgentRunStatus.SUCCEEDED, input_message="Workspace A only run.",
    final_response="Workspace A only response.",
    started_at=timezone.now(), completed_at=timezone.now(),
)

# Tool Executions domain (Phase 20 Chunk 2) — real ToolDefinition/ToolBinding/
# ToolExecution rows on the Workspace B succeeded/running runs, so the
# real-backend smoke can prove tenant-scoped trace visibility, redaction,
# attempt counts, and non-terminal polling against the actual API.
# sync_tool_definitions() is the same idempotent call the real data
# migration/seed_demo command makes (tools/services.py) — never a live
# provider call, just mirroring the code-owned tool registry into the DB.
sync_tool_definitions()
echo_def = ToolDefinition.objects.get(key="demo.echo")
flaky_def = ToolDefinition.objects.get(key="demo.flaky")
echo_binding = ToolBinding.objects.create(
    agent_version=ws_b_agent_version, tool_definition=echo_def, enabled=True,
)
flaky_binding = ToolBinding.objects.create(
    agent_version=ws_b_agent_version, tool_definition=flaky_def, enabled=True,
)
ws_b_tool_execution_succeeded = ToolExecution.objects.create(
    workspace=ws_b, agent_run=ws_b_agent_run_succeeded, agent_version=ws_b_agent_version,
    tool_definition=echo_def, tool_binding=echo_binding, status=ToolExecutionStatus.SUCCEEDED,
    # Real backend redaction (common/redaction.py redact()) applied here
    # exactly as tools/execution.py applies it before persisting — a FAKE
    # secret-shaped value, never a real one, proving the actual contract
    # rather than a frontend-invented placeholder.
    arguments_redacted=redact({"message": "hello", "api_key": "fake-not-a-real-secret"}),
    result_redacted={"echoed": "hello"},
    attempt_count=1, timeout_seconds=5,
    started_at=timezone.now(), completed_at=timezone.now(), duration_ms=42,
)
# A second, failed tool execution on the same run — multiple real attempts
# (demo.flaky's own deterministic retry semantics, tools/demo_tools.py),
# and a safe, non-traceback error message.
ws_b_tool_execution_failed = ToolExecution.objects.create(
    workspace=ws_b, agent_run=ws_b_agent_run_succeeded, agent_version=ws_b_agent_version,
    tool_definition=flaky_def, tool_binding=flaky_binding, status=ToolExecutionStatus.FAILED,
    arguments_redacted={"fail_attempts": 5}, result_redacted={},
    attempt_count=4, timeout_seconds=1,
    started_at=timezone.now(), completed_at=timezone.now(),
    error_code="tool_execution_failed", error_message_safe="Deterministic demo failure.",
)
# A read-only approval-context fixture on the non-terminal (running) run —
# a real ToolExecutionStatus value; the underlying ApprovalRequest/
# PolicyEvaluation/RiskAssessment rows a real Phase 8 approval gate would
# also create are intentionally not replicated here (Chunk 2 renders only
# ToolExecution's own status/error_code — see frontend/README.md).
ws_b_tool_execution_waiting = ToolExecution.objects.create(
    workspace=ws_b, agent_run=ws_b_agent_run_running, agent_version=ws_b_agent_version,
    tool_definition=echo_def, tool_binding=echo_binding,
    status=ToolExecutionStatus.WAITING_FOR_APPROVAL,
    arguments_redacted={"message": "please refund order #4821"}, result_redacted={},
    attempt_count=0, timeout_seconds=5, started_at=timezone.now(),
)

# Approvals domain (Phase 20 Chunk 3) — real ApprovalRequest rows, built
# directly via the ORM rather than through the orchestration/policy-gate
# path (which would require a live-or-faked payment provider call), exactly
# mirroring the real fields approvals.services.create_or_reuse_approval_request
# persists for an actual payment.refund gate — verified empirically against
# the real ApprovalRequestSerializer before writing this fixture (see the
# Chunk 3 report). Workspace A's primary membership is OWNER (rank 3,
# satisfies any required_role), used for the real Approve/Reject/expiry/
# concurrent-decision E2E; Workspace B's is SUPPORT_AGENT (rank 0, outside
# the approval-authority ranking entirely), used for the real
# permission-denial E2E. A dedicated AgentRun per workspace (never
# ws_a_agent_run/ws_b_agent_run_running) — Chunk 2's own E2E spec asserts
# ws_a_agent_run has NO tool executions, and ws_b_agent_run_running already
# carries its own Chunk 2 waiting-approval ToolExecution fixture; reusing
# either would silently break that chunk's invariant.
refund_def = ToolDefinition.objects.get(key="payment.refund")
ws_a_approvals_run = AgentRun.objects.create(
    workspace=ws_a, agent_version=ws_a_agent_version, trigger=AgentRunTrigger.MANUAL,
    status=AgentRunStatus.RUNNING, input_message="Process a batch of refund requests.",
    started_at=timezone.now(),
)
ws_b_approvals_run = AgentRun.objects.create(
    workspace=ws_b, agent_version=ws_b_agent_version, trigger=AgentRunTrigger.MANUAL,
    status=AgentRunStatus.RUNNING, input_message="Process a refund request.",
    started_at=timezone.now(),
)
ws_a_refund_binding = ToolBinding.objects.create(
    agent_version=ws_a_agent_version, tool_definition=refund_def, enabled=True,
)
ws_b_refund_binding = ToolBinding.objects.create(
    agent_version=ws_b_agent_version, tool_definition=refund_def, enabled=True,
)

def make_pending_approval(*, workspace, agent_run, agent_version, binding, required_role, summary):
    execution = ToolExecution.objects.create(
        workspace=workspace, agent_run=agent_run, agent_version=agent_version,
        tool_definition=refund_def, tool_binding=binding,
        status=ToolExecutionStatus.WAITING_FOR_APPROVAL,
        arguments_redacted=redact({
            "payment_reference": "pi_1", "amount_minor": 10000, "currency": "usd",
            "api_key": "fake-not-a-real-secret",
        }),
        result_redacted={}, attempt_count=0, timeout_seconds=10, started_at=timezone.now(),
    )
    risk = RiskAssessment.objects.create(
        workspace=workspace, tool_execution=execution, tool_key="payment.refund",
        base_risk=RiskLevel.CRITICAL, effective_risk=RiskLevel.CRITICAL,
        side_effect_type=SideEffectType.FINANCIAL,
    )
    evaluation = PolicyEvaluation.objects.create(
        workspace=workspace, tool_execution=execution, risk_assessment=risk, policy_version=None,
        decision=PolicyEffect.REQUIRE_APPROVAL,
        decision_code="system_default_financial_requires_approval",
        safe_reason="Financial actions require approval.",
    )
    return ApprovalRequest.objects.create(
        workspace=workspace, tool_execution=execution, policy_evaluation=evaluation, risk_assessment=risk,
        requested_by=None, required_role=required_role, summary=summary,
        safe_context={
            "tool_key": "payment.refund", "tool_display_name": "Payment refund",
            "risk_level": RiskLevel.CRITICAL, "side_effect_type": SideEffectType.FINANCIAL,
            "policy_reason": "Financial actions require approval.",
            "arguments": redact({
                "payment_reference": "pi_1", "amount_minor": 10000, "currency": "usd",
                "api_key": "fake-not-a-real-secret",
            }),
        },
        expires_at=timezone.now() + timedelta(hours=1),
    )

ws_a_approval_approve = make_pending_approval(
    workspace=ws_a, agent_run=ws_a_approvals_run, agent_version=ws_a_agent_version,
    binding=ws_a_refund_binding, required_role=WorkspaceRole.ADMIN,
    summary="payment.refund: amount_minor=10000, currency=usd (approve)",
)
ws_a_approval_reject = make_pending_approval(
    workspace=ws_a, agent_run=ws_a_approvals_run, agent_version=ws_a_agent_version,
    binding=ws_a_refund_binding, required_role=WorkspaceRole.ADMIN,
    summary="payment.refund: amount_minor=10000, currency=usd (reject)",
)
ws_a_approval_concurrent = make_pending_approval(
    workspace=ws_a, agent_run=ws_a_approvals_run, agent_version=ws_a_agent_version,
    binding=ws_a_refund_binding, required_role=WorkspaceRole.ADMIN,
    summary="payment.refund: amount_minor=10000, currency=usd (concurrent)",
)
ws_a_approval_expired = make_pending_approval(
    workspace=ws_a, agent_run=ws_a_approvals_run, agent_version=ws_a_agent_version,
    binding=ws_a_refund_binding, required_role=WorkspaceRole.ADMIN,
    summary="payment.refund: amount_minor=10000, currency=usd (expired)",
)
ApprovalRequest.objects.filter(pk=ws_a_approval_expired.id).update(
    status=ApprovalStatus.EXPIRED,
    created_at=timezone.now() - timedelta(hours=3),
    expires_at=timezone.now() - timedelta(hours=2),
    resolved_at=timezone.now() - timedelta(hours=2),
)
ws_a_approval_decided = make_pending_approval(
    workspace=ws_a, agent_run=ws_a_approvals_run, agent_version=ws_a_agent_version,
    binding=ws_a_refund_binding, required_role=WorkspaceRole.ADMIN,
    summary="payment.refund: amount_minor=10000, currency=usd (already decided)",
)
ApprovalDecision.objects.create(
    approval_request=ws_a_approval_decided, decision=ApprovalDecisionValue.APPROVE,
    decided_by=primary, safe_comment="Confirmed with customer.",
)
ApprovalRequest.objects.filter(pk=ws_a_approval_decided.id).update(
    status=ApprovalStatus.APPROVED, resolved_at=timezone.now(),
)
ws_b_approval_pending = make_pending_approval(
    workspace=ws_b, agent_run=ws_b_approvals_run, agent_version=ws_b_agent_version,
    binding=ws_b_refund_binding, required_role=WorkspaceRole.SUPPORT_MANAGER,
    summary="payment.refund: amount_minor=10000, currency=usd (permission test)",
)
# Phase 20 Chunk 4: a dedicated fixture for the keyboard-only AI-operations
# journey (e2e/keyboard-journey.spec.ts) — never reused by any other spec's
# Approve/Reject, so that test's own decision doesn't race or collide with
# approvals.spec.ts's mutation of ws_a_approval_approve/ws_a_approval_reject.
ws_a_approval_keyboard = make_pending_approval(
    workspace=ws_a, agent_run=ws_a_approvals_run, agent_version=ws_a_agent_version,
    binding=ws_a_refund_binding, required_role=WorkspaceRole.ADMIN,
    summary="payment.refund: amount_minor=10000, currency=usd (keyboard journey)",
)
# Phase 20 Chunk 4: a dedicated fixture for the mobile (375px) Approval
# usability test (e2e/responsive.spec.ts) — never reused by approvals.spec.ts,
# for the same collision-avoidance reason as ws_a_approval_keyboard above.
ws_a_approval_mobile = make_pending_approval(
    workspace=ws_a, agent_run=ws_a_approvals_run, agent_version=ws_a_agent_version,
    binding=ws_a_refund_binding, required_role=WorkspaceRole.ADMIN,
    summary="payment.refund: amount_minor=10000, currency=usd (mobile)",
)

# Human Handoff domain (Phase 20 Chunk 3) — real HumanHandoff rows with real
# Conversation/AgentRun/Ticket relations, so the real-backend smoke can prove
# tenant-scoped visibility and the real cross-links (never a guessed join —
# HumanHandoffSerializer exposes conversation_id/agent_run_id/ticket_id
# directly, unlike ApprovalRequest, which exposes none).
ws_b_handoff_pending = HumanHandoff.objects.create(
    workspace=ws_b, conversation=ws_b_unassigned_conversation, agent_run=ws_b_agent_run_running,
    status=HumanHandoffStatus.PENDING, reason_code=HumanHandoffReason.CUSTOMER_REQUESTED,
    safe_summary="Customer explicitly asked to speak with a human agent.",
)
ws_b_handoff_resolved = HumanHandoff.objects.create(
    workspace=ws_b, conversation=ws_b_conversation, agent_run=ws_b_agent_run_succeeded,
    ticket=ws_b_ticket, status=HumanHandoffStatus.RESOLVED,
    reason_code=HumanHandoffReason.POLICY_ESCALATION,
    safe_summary="Refund required manager sign-off before this workspace's policy allowed it.",
    assigned_to=membership_b, resolved_at=timezone.now(),
)
ws_a_handoff_pending = HumanHandoff.objects.create(
    workspace=ws_a, conversation=ws_a_conversation, status=HumanHandoffStatus.PENDING,
    reason_code=HumanHandoffReason.LOW_CONFIDENCE,
    safe_summary="Retrieval confidence was too low to answer safely.",
)

# Knowledge/RAG domain (Phase 21 Chunk 1) — real KnowledgeSource/
# KnowledgeDocument rows with real cross-workspace data, created directly
# via the ORM (never through the upload endpoint, which would require a real
# multipart file and would trigger real ingestion via Celery) so the
# real-backend smoke can prove tenant isolation, source/status filters, and
# safe metadata rendering against the actual API. Rows cascade-delete with
# their workspace (KnowledgeSource.workspace and KnowledgeDocument.workspace
# are both on_delete=CASCADE); KnowledgeDocument.source is on_delete=PROTECT
# but that only guards a source-only delete — Workspace.delete() collects
# both models via their own direct workspace CASCADE, so no special
# ordering is needed here (same reasoning as HumanHandoff above).
ws_b_knowledge_source = KnowledgeSource.objects.create(
    workspace=ws_b, name="Support Macros", description="Canned refund/shipping responses.",
    source_type=KnowledgeSourceType.UPLOAD, is_active=True,
)
ws_b_knowledge_document_ready = KnowledgeDocument.objects.create(
    workspace=ws_b, source=ws_b_knowledge_source, title="Refund policy",
    original_filename="refund-policy.txt", stored_file="knowledge/e2e/refund-policy.txt",
    content_type="text/plain", file_size=512, content_sha256="b" * 64,
    status=KnowledgeDocumentStatus.READY, extracted_char_count=480, chunk_count=3,
    last_ingested_at=timezone.now(),
    # Phase 21 Chunk 1 content-safety fixture: HTML/script-looking real
    # metadata, to prove end to end (not just via unit test) that it is
    # rendered as inert plain text, never interpreted as markup.
    metadata={"note": "<script>window.__xss_marker = true;</script>"},
)
ws_b_knowledge_document_failed = KnowledgeDocument.objects.create(
    workspace=ws_b, source=ws_b_knowledge_source, title="Malformed upload",
    original_filename="broken.pdf", stored_file="knowledge/e2e/broken.pdf",
    content_type="application/pdf", file_size=64, content_sha256="c" * 64,
    status=KnowledgeDocumentStatus.FAILED, last_error_code="knowledge_malformed_pdf",
    last_error_message_safe="The PDF is malformed or unreadable.",
)
ws_a_knowledge_source = KnowledgeSource.objects.create(
    workspace=ws_a, name="Workspace A Only Source", source_type=KnowledgeSourceType.MANUAL,
)
ws_a_knowledge_document = KnowledgeDocument.objects.create(
    workspace=ws_a, source=ws_a_knowledge_source, title="Workspace A only document",
    original_filename="a-only.txt", stored_file="knowledge/e2e/a-only.txt",
    content_type="text/plain", file_size=32, content_sha256="d" * 64,
    status=KnowledgeDocumentStatus.READY, extracted_char_count=30, chunk_count=1,
    last_ingested_at=timezone.now(),
)
# Phase 21 Chunk 2: a real failed document in Workspace A (whose primary
# membership is OWNER — canManageKnowledge) so the real-backend Retry E2E
# has something legitimately retryable, distinct from Workspace B's own
# failed-document fixture (ws_b_knowledge_document_failed, used by Chunk 1's
# read-only failed-state test).
ws_a_knowledge_document_failed = KnowledgeDocument.objects.create(
    workspace=ws_a, source=ws_a_knowledge_source, title="Workspace A retryable failure",
    original_filename="a-broken.pdf", stored_file="knowledge/e2e/a-broken.pdf",
    content_type="application/pdf", file_size=64, content_sha256="e" * 64,
    status=KnowledgeDocumentStatus.FAILED, last_error_code="knowledge_malformed_pdf",
    last_error_message_safe="The PDF is malformed or unreadable.",
)
# retry_document (knowledge/services.py) requires a real, real prior
# ingestion job to re-queue (it re-uses the most recent one) — without this,
# the real Retry E2E would hit a genuine 409 "No ingestion job exists",
# which is not the scenario this fixture is for.
KnowledgeIngestionJob.objects.create(
    workspace=ws_a, document=ws_a_knowledge_document_failed,
    status=KnowledgeIngestionStatus.FAILED, idempotency_key="e2e-a-broken-job",
    error_code="knowledge_malformed_pdf", safe_error_message="The PDF is malformed or unreadable.",
)
# Phase 21 Chunk 2A: a real, genuinely non-terminal (PROCESSING) document in
# Workspace A, created directly via the ORM rather than through a real
# upload — a real upload's genuine non-terminal window is too short and
# timing-dependent to assert against reliably (the real Celery worker may
# race straight through it), and the master prompt explicitly forbids
# slowing production code or adding arbitrary sleeps to widen that window.
# This row has no associated KnowledgeIngestionJob, so nothing (no real
# Celery task references it) will ever move it out of PROCESSING — it stays
# non-terminal for the lifetime of this fixture, which is exactly what the
# active-processing workspace-isolation test needs to prove: a real backend
# non-terminal state, safely and deterministically held in place.
ws_a_knowledge_document_processing = KnowledgeDocument.objects.create(
    workspace=ws_a, source=ws_a_knowledge_source, title="Workspace A actively processing",
    original_filename="a-processing.txt", stored_file="knowledge/e2e/a-processing.txt",
    content_type="text/plain", file_size=48, content_sha256="f" * 64,
    status=KnowledgeDocumentStatus.PROCESSING,
)

print(json.dumps({
    "primaryEmail": primary.email,
    "primaryPassword": PASSWORD,
    "zeroEmail": zero.email,
    "zeroPassword": PASSWORD,
    "workspaceAId": str(ws_a.id),
    "workspaceAName": ws_a.name,
    "workspaceBId": str(ws_b.id),
    "workspaceBName": ws_b.name,
    # Memberships list from /auth/me/ is ordered by -created_at (selectors.py
    # list_active_memberships_for_user) - the LAST-created membership (B)
    # sorts first and is the deterministic default active workspace, not A.
    "defaultWorkspaceName": ws_b.name,
    "defaultWorkspaceId": str(ws_b.id),
    "otherWorkspaceName": ws_a.name,
    "otherWorkspaceId": str(ws_a.id),
    "workspaceACustomerId": str(ws_a_customer.id),
    "workspaceACustomerName": ws_a_customer.display_name,
    "workspaceBCustomerId": str(ws_b_customer.id),
    "workspaceBCustomerName": ws_b_customer.display_name,
    "workspaceBConversationId": str(ws_b_conversation.id),
    "workspaceBConversationSubject": ws_b_conversation.subject,
    "workspaceBUnassignedConversationId": str(ws_b_unassigned_conversation.id),
    "workspaceBUnassignedConversationSubject": ws_b_unassigned_conversation.subject,
    "workspaceAConversationId": str(ws_a_conversation.id),
    "workspaceAConversationSubject": ws_a_conversation.subject,
    "workspaceBTicketId": str(ws_b_ticket.id),
    "workspaceBTicketSubject": ws_b_ticket.subject,
    "workspaceBResolvedTicketId": str(ws_b_resolved_ticket.id),
    "workspaceBResolvedTicketSubject": ws_b_resolved_ticket.subject,
    "workspaceATicketId": str(ws_a_ticket.id),
    "workspaceATicketSubject": ws_a_ticket.subject,
    "workspaceBAgentRunSucceededId": str(ws_b_agent_run_succeeded.id),
    "workspaceBAgentRunRunningId": str(ws_b_agent_run_running.id),
    "workspaceAAgentRunId": str(ws_a_agent_run.id),
    "workspaceAAgentRunResponse": ws_a_agent_run.final_response,
    "workspaceBToolExecutionSucceededId": str(ws_b_tool_execution_succeeded.id),
    "workspaceBToolExecutionFailedId": str(ws_b_tool_execution_failed.id),
    "workspaceBToolExecutionWaitingId": str(ws_b_tool_execution_waiting.id),
    "workspaceAApprovalApproveId": str(ws_a_approval_approve.id),
    "workspaceAApprovalRejectId": str(ws_a_approval_reject.id),
    "workspaceAApprovalConcurrentId": str(ws_a_approval_concurrent.id),
    "workspaceAApprovalExpiredId": str(ws_a_approval_expired.id),
    "workspaceAApprovalDecidedId": str(ws_a_approval_decided.id),
    "workspaceBApprovalPendingId": str(ws_b_approval_pending.id),
    "workspaceAApprovalKeyboardId": str(ws_a_approval_keyboard.id),
    "workspaceAApprovalMobileId": str(ws_a_approval_mobile.id),
    "workspaceBHandoffPendingId": str(ws_b_handoff_pending.id),
    "workspaceBHandoffResolvedId": str(ws_b_handoff_resolved.id),
    "workspaceAHandoffPendingId": str(ws_a_handoff_pending.id),
    "workspaceBKnowledgeSourceId": str(ws_b_knowledge_source.id),
    "workspaceBKnowledgeSourceName": ws_b_knowledge_source.name,
    "workspaceBKnowledgeDocumentReadyId": str(ws_b_knowledge_document_ready.id),
    "workspaceBKnowledgeDocumentFailedId": str(ws_b_knowledge_document_failed.id),
    "workspaceAKnowledgeDocumentId": str(ws_a_knowledge_document.id),
    "workspaceAKnowledgeSourceId": str(ws_a_knowledge_source.id),
    "workspaceAKnowledgeDocumentFailedId": str(ws_a_knowledge_document_failed.id),
    "workspaceAKnowledgeDocumentProcessingId": str(ws_a_knowledge_document_processing.id),
}))
`;

export default async function globalSetup(): Promise<void> {
  const output = execFileSync(PYTHON, ["manage.py", "shell", "-c", SETUP_SCRIPT], {
    cwd: BACKEND_ROOT,
    encoding: "utf-8",
  });
  const jsonLine = output
    .trim()
    .split("\n")
    .filter((line) => line.trim().startsWith("{"))
    .pop();
  if (!jsonLine) {
    throw new Error(`E2E global setup: could not find JSON output from Django shell.\n${output}`);
  }
  fs.writeFileSync(DATA_FILE, jsonLine);
}
