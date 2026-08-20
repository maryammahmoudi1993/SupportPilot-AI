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

import uuid

from accounts.models import User
from conversations.models import Conversation, Message
from workspaces.models import Workspace

from . import services
from .errors import AgentError
from .models import AgentRun, AgentRunTrigger, AgentVersion

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
    actor: User,
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
    """
    if trigger_message.conversation_id != conversation.id:
        raise TriggerMessageMismatchError()
    if trigger_message.workspace_id != workspace.id:
        raise TriggerMessageMismatchError()
    if conversation.workspace_id != workspace.id:
        raise TriggerMessageMismatchError()

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
    return services.execute_agent_run(run_id)


def resume_support_agent_run(approval_request_id: uuid.UUID | str) -> str:
    """Resume the run a just-granted approval belongs to.

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
