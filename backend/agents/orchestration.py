"""The support-agent orchestration service boundary (Phase 9, section 79-80).

This module is the single entry point that connects a customer message to
a bounded agent run. Views and Celery tasks call *this* module, never
``agents.services`` directly, for anything conversation-triggered — the
low-level run lifecycle (claim/execute/resume/cancel, budget enforcement,
policy/approval gating) remains exactly as Phase 5-8 built it; this module
only adds the conversation-aware framing around it:

* :func:`start_support_agent_run` resolves the triggering message and
  idempotently creates (or reuses) the one logical ``AgentRun`` for it.
* :func:`execute_support_agent_run` and :func:`resume_support_agent_run` are
  the stable orchestration-level names for running/resuming a run — thin
  today, but the fixed seam later Phase 9 blocks (context assembly, RAG,
  the bounded multi-tool loop) extend without changing any caller.
* :func:`cancel_support_agent_run` is the stable orchestration-level name for
  cancelling a run.

No hidden reasoning is introduced here: every field this module reads or
writes is already a safe, structured field on ``AgentRun``/``Message``.
"""

from __future__ import annotations

import logging
import time
import uuid

from accounts.models import User
from conversations.models import Conversation, Message
from workspaces.models import Workspace

from . import services
from .context import (
    InvalidTriggerMessageError,
    build_conversation_context,
    validate_trigger_message,
)
from .errors import AgentError
from .llm_context import build_agent_llm_context
from .models import AgentRun, AgentRunTrigger, AgentVersion
from .rag import retrieve_agent_knowledge
from .tool_catalog import ToolCatalogConfigurationError, get_bound_tool_descriptors

logger = logging.getLogger("supportpilot")

__all__ = [
    "start_support_agent_run",
    "execute_support_agent_run",
    "resume_support_agent_run",
    "cancel_support_agent_run",
]


class TriggerMessageMismatchError(AgentError):
    code = "trigger_message_mismatch"
    safe_message = "The trigger message does not belong to this conversation."


def start_support_agent_run(
    *,
    workspace: Workspace,
    actor: User | None,
    conversation: Conversation,
    trigger_message: Message,
    agent_version: AgentVersion,
    request_id: str | None = None,
) -> AgentRun:
    """Start (or idempotently reuse) the one logical ``AgentRun`` for
    ``trigger_message`` (section 17-19, 80-81).

    Every server-controlled scoping fact — workspace, conversation, agent
    version status/tenancy — is validated here or in ``create_agent_run``;
    none of it is ever taken from client-suppliable fields on the message
    itself.

    ``actor`` is ``None`` for a channel-triggered run (Phase 13,
    ``channel_ingress.services.process_inbound_channel_event``): an inbound
    customer message has no authenticated staff user behind it, exactly like
    ``AgentRun.created_by`` already tolerates for every other non-staff
    trigger (``on_delete=SET_NULL``).
    """
    if trigger_message.conversation_id != conversation.id:
        raise TriggerMessageMismatchError()
    if trigger_message.workspace_id != workspace.id:
        raise TriggerMessageMismatchError()
    if conversation.workspace_id != workspace.id:
        raise TriggerMessageMismatchError()
    validate_trigger_message(
        workspace=workspace, conversation=conversation, trigger_message=trigger_message
    )

    return services.create_agent_run(
        workspace=workspace,
        agent_version=agent_version,
        actor=actor,
        input_message=trigger_message.body,
        trigger=AgentRunTrigger.CONVERSATION,
        conversation=conversation,
        trigger_message=trigger_message,
        request_id=request_id,
    )


def execute_support_agent_run(run_id: uuid.UUID | str) -> AgentRun:
    """Run a pending support-agent run to a terminal (or paused) state.

    Safe to call more than once for the same ``run_id`` — see
    ``agents.services.execute_agent_run``.
    """
    run = services.claim_agent_run(run_id)
    if run is None:
        return AgentRun.objects.get(pk=run_id)

    conversation = run.conversation
    trigger_message = run.trigger_message
    if conversation is None or trigger_message is None:
        return services.execute_claimed_agent_run(run)

    # Phase 9 Block 5 (section 59-61): a conversation already actively
    # escalated to a human never gets a second autonomous execution for a
    # new inbound message — checked before any RAG/LLM cost is spent.
    from tickets.selectors import active_handoff_for_conversation

    if active_handoff_for_conversation(conversation=conversation) is not None:
        return services.complete_run_via_existing_active_handoff(run)

    try:
        conversation_context = build_conversation_context(
            workspace=run.workspace,
            conversation=conversation,
            trigger_message=trigger_message,
        )
    except InvalidTriggerMessageError as exc:
        return services.fail_claimed_agent_run(run=run, code=exc.code, message=exc.safe_message)
    services.record_agent_operational_step(
        run=run,
        event="conversation_context_prepared",
        safe_metadata={
            "message_count": len(conversation_context.messages),
            "available_message_count": conversation_context.available_message_count,
            "character_count": conversation_context.character_count,
            "truncated": conversation_context.truncated,
        },
    )

    try:
        tool_descriptors = get_bound_tool_descriptors(
            agent_version=run.agent_version, workspace=run.workspace
        )
    except ToolCatalogConfigurationError as exc:
        return services.fail_claimed_agent_run(run=run, code=exc.code, message=exc.safe_message)
    services.record_agent_operational_step(
        run=run,
        event="tool_catalog_prepared",
        safe_metadata={
            "tool_count": len(tool_descriptors),
            "tool_keys": [descriptor.key for descriptor in tool_descriptors],
        },
    )

    retrieval_started = time.monotonic()
    try:
        knowledge_context = retrieve_agent_knowledge(
            workspace=run.workspace,
            query=trigger_message.body,
            actor=run.created_by,
        )
    except Exception:
        logger.exception(
            "agent_knowledge_retrieval_failed",
            extra={
                "workspace_id": str(run.workspace_id),
                "conversation_id": str(conversation.id),
                "trigger_message_id": str(trigger_message.id),
                "agent_run_id": str(run.id),
            },
        )
        return services.fail_claimed_agent_run(
            run=run,
            code="knowledge_retrieval_failed",
            message="Knowledge retrieval failed safely.",
        )
    retrieval_duration_ms = int((time.monotonic() - retrieval_started) * 1000)
    services.record_agent_operational_step(
        run=run,
        event="knowledge_retrieved",
        safe_metadata={
            "retrieval_event_id": str(knowledge_context.retrieval_event_id),
            "retrieval_count": len(knowledge_context.references),
            "rag_character_count": knowledge_context.character_count,
            "truncated": knowledge_context.truncated,
            "chunk_ids": [str(item.chunk_id) for item in knowledge_context.references],
            "source_ids": [str(item.source_id) for item in knowledge_context.references],
            "duration_ms": retrieval_duration_ms,
        },
    )

    llm_context = build_agent_llm_context(
        agent_version=run.agent_version,
        conversation=conversation_context,
        knowledge=knowledge_context,
    )
    services.record_agent_operational_step(
        run=run,
        event="llm_context_prepared",
        safe_metadata={
            "message_count": len(llm_context.messages),
            "citation_count": len(llm_context.citations),
            "rag_character_count": llm_context.rag_character_count,
        },
    )
    logger.info(
        "agent_context_prepared",
        extra={
            "workspace_id": str(run.workspace_id),
            "conversation_id": str(conversation.id),
            "trigger_message_id": str(trigger_message.id),
            "agent_run_id": str(run.id),
            "context_message_count": len(conversation_context.messages),
            "context_truncated": conversation_context.truncated,
            "retrieval_count": len(knowledge_context.references),
            "retrieval_duration_ms": retrieval_duration_ms,
        },
    )
    return services.execute_claimed_agent_run(
        run,
        initial_messages=llm_context.messages,
        output_metadata={"citations": list(llm_context.citations)},
        tool_descriptors=tool_descriptors,
    )


def resume_support_agent_run(approval_request_id: uuid.UUID | str) -> str:
    """Continue the run an approval decision (approve or reject) or its
    expiry just resolved (Phase 9 Block 4).

    Safe to call more than once for the same ``approval_request_id`` — see
    ``agents.services.resume_agent_run_after_approval``.
    """
    return services.resume_agent_run_after_approval(approval_request_id)


def cancel_support_agent_run(
    *, workspace: Workspace, run: AgentRun, actor: User, request_id: str | None = None
) -> AgentRun:
    """Cancel a support-agent run, releasing any pending approval/handoff it
    holds. See ``agents.services.cancel_agent_run``."""
    return services.cancel_agent_run(
        workspace=workspace, run=run, actor=actor, request_id=request_id
    )
