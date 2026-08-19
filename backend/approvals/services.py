"""Approval lifecycle services (Phase 8).

``create_or_reuse_approval_request`` is called only from the tool-execution
policy gate (``tools/execution.py``). Every other function here is called
from the approvals API/Celery task layer. Every state transition re-reads
the row under ``select_for_update`` inside a transaction before writing —
the same pattern ``agents/services.py`` and ``tools/execution.py`` already
use — which is what makes concurrent approve/reject/expire/cancel races
safe (section 41-42, 90-93).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import User
from audit.models import AuditAction
from audit.services import record_event
from common.redaction import redact
from tools.models import ToolExecution, ToolExecutionStatus
from workspaces.models import WorkspaceRole

from .errors import (
    ApprovalAlreadyResolvedError,
    ApprovalCancelledError,
    ApprovalExpiredError,
    ApprovalPermissionDeniedError,
    ApprovalSelfApprovalForbiddenError,
)
from .models import (
    ApprovalDecision,
    ApprovalDecisionValue,
    ApprovalRequest,
    ApprovalStatus,
)

MAX_SUMMARY_ARGUMENT_CHARS = 300

# Approval authority is a linear escalation distinct from the workspace's
# general non-hierarchical capability RBAC (section 47-48): a role that can
# decide a lower-risk approval can always decide it, and a higher role may
# decide anything a lower one could. Only these three roles ever appear as
# ``required_role`` (see ``policies/defaults.py``).
_APPROVAL_ROLE_RANK: dict[str, int] = {
    WorkspaceRole.SUPPORT_MANAGER: 1,
    WorkspaceRole.ADMIN: 2,
    WorkspaceRole.OWNER: 3,
}


def role_satisfies_requirement(*, actor_role: str, required_role: str) -> bool:
    return _APPROVAL_ROLE_RANK.get(actor_role, 0) >= _APPROVAL_ROLE_RANK.get(required_role, 99)


# ---------------------------------------------------------------------------
# Creation — called only from the tool-execution policy gate.
# ---------------------------------------------------------------------------


def create_or_reuse_approval_request(
    *,
    execution: ToolExecution,
    agent_run,
    evaluation,
    risk_assessment,
    required_role: str,
    ttl_seconds: int,
    canonical_arguments: dict[str, Any],
    tool,
) -> ApprovalRequest:
    """One ``ApprovalRequest`` per ``ToolExecution`` (section 11) — the
    ``OneToOneField`` makes a second call for the same execution return the
    existing row rather than raising, so repeated model/tool attempts for
    the same logical action never create approval spam."""
    existing = ApprovalRequest.objects.filter(tool_execution=execution).first()
    if existing is not None:
        return existing

    safe_arguments = redact(
        canonical_arguments, extra_keys=frozenset(tool.spec.input_sensitive_fields)
    )
    summary = _build_summary(tool_key=tool.spec.key, arguments=safe_arguments)
    safe_context = {
        "tool_key": tool.spec.key,
        "tool_display_name": tool.spec.display_name,
        "risk_level": risk_assessment.effective_risk,
        "side_effect_type": risk_assessment.side_effect_type,
        "policy_reason": evaluation.safe_reason,
        "arguments": safe_arguments,
    }
    with transaction.atomic():
        approval = ApprovalRequest.objects.create(
            workspace=execution.workspace,
            tool_execution=execution,
            policy_evaluation=evaluation,
            risk_assessment=risk_assessment,
            requested_by=agent_run.created_by,
            required_role=required_role,
            summary=summary,
            safe_context=safe_context,
            arguments_fingerprint=execution.arguments_fingerprint,
            expires_at=timezone.now() + timedelta(seconds=ttl_seconds),
        )
        record_event(
            action=AuditAction.APPROVAL_REQUESTED,
            target_type="approval_request",
            target_id=approval.id,
            actor=agent_run.created_by,
            workspace=execution.workspace,
            metadata={
                "approval_request_id": str(approval.id),
                "tool_execution_id": str(execution.id),
                "tool_key": tool.spec.key,
                "required_role": required_role,
            },
            request_id=agent_run.correlation_id or None,
        )
    return approval


def _build_summary(*, tool_key: str, arguments: dict[str, Any]) -> str:
    parts = [f"{k}={v}" for k, v in sorted(arguments.items())]
    body = ", ".join(parts)[:MAX_SUMMARY_ARGUMENT_CHARS]
    return f"{tool_key}: {body}"[:500]


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


def decide_approval(
    *,
    workspace,
    approval_request: ApprovalRequest,
    actor: User,
    actor_role: str,
    decision: str,
    comment: str = "",
    request_id: str | None = None,
) -> ApprovalRequest:
    with transaction.atomic():
        locked = ApprovalRequest.objects.select_for_update().get(pk=approval_request.pk)
        _enforce_expiry(locked)

        if locked.status == ApprovalStatus.CANCELLED:
            raise ApprovalCancelledError()
        if locked.status in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED):
            resolved_value = (
                ApprovalDecisionValue.APPROVE
                if locked.status == ApprovalStatus.APPROVED
                else ApprovalDecisionValue.REJECT
            )
            if resolved_value == decision:
                # Idempotent replay (section 42): a duplicate identical
                # decision from a network retry is not an error.
                return locked
            raise ApprovalAlreadyResolvedError()

        # status == PENDING — current DB membership is authoritative, never
        # a cached/stale role (section 50).
        if locked.requested_by_id and locked.requested_by_id == actor.id:
            raise ApprovalSelfApprovalForbiddenError()
        if not role_satisfies_requirement(
            actor_role=actor_role, required_role=locked.required_role
        ):
            raise ApprovalPermissionDeniedError()

        try:
            with transaction.atomic():
                ApprovalDecision.objects.create(
                    approval_request=locked,
                    decision=decision,
                    decided_by=actor,
                    safe_comment=comment[:1000],
                )
        except IntegrityError:
            # Lost a concurrent race for the one-decision-per-request slot
            # (section 41, 90-91) — the winning decision is authoritative.
            locked.refresh_from_db()
            raise ApprovalAlreadyResolvedError() from None

        locked.status = (
            ApprovalStatus.APPROVED
            if decision == ApprovalDecisionValue.APPROVE
            else ApprovalStatus.REJECTED
        )
        locked.resolved_at = timezone.now()
        locked.save(update_fields=["status", "resolved_at", "updated_at"])
        record_event(
            action=(
                AuditAction.APPROVAL_APPROVED
                if decision == ApprovalDecisionValue.APPROVE
                else AuditAction.APPROVAL_REJECTED
            ),
            target_type="approval_request",
            target_id=locked.id,
            actor=actor,
            workspace=workspace,
            metadata={"approval_request_id": str(locked.id)},
            request_id=request_id,
        )

        if decision == ApprovalDecisionValue.REJECT:
            _terminate_execution(
                locked, error_code="approval_rejected", error_message="This action was rejected."
            )
        else:
            transaction.on_commit(lambda: _dispatch_resume(locked.id))

    return locked


def _enforce_expiry(locked: ApprovalRequest) -> None:
    """Section 44: expiry is checked from the wall clock, never trusted from
    stale ``status`` alone."""
    if locked.status != ApprovalStatus.PENDING:
        return
    if timezone.now() >= locked.expires_at:
        locked.status = ApprovalStatus.EXPIRED
        locked.resolved_at = timezone.now()
        locked.save(update_fields=["status", "resolved_at", "updated_at"])
        _terminate_execution(
            locked, error_code="approval_expired", error_message="The approval request expired."
        )
        record_event(
            action=AuditAction.APPROVAL_EXPIRED,
            target_type="approval_request",
            target_id=locked.id,
            actor=None,
            workspace=locked.workspace,
            metadata={"approval_request_id": str(locked.id)},
        )
        raise ApprovalExpiredError()


def expire_stale_approvals(*, now=None) -> int:
    """Periodic sweep (section 45) — safe to call as often or as rarely as
    desired; each row is only ever transitioned once."""
    now = now or timezone.now()
    count = 0
    stale_ids = list(
        ApprovalRequest.objects.filter(
            status=ApprovalStatus.PENDING, expires_at__lte=now
        ).values_list("id", flat=True)
    )
    for approval_id in stale_ids:
        with transaction.atomic():
            locked = ApprovalRequest.objects.select_for_update().get(pk=approval_id)
            if locked.status != ApprovalStatus.PENDING or locked.expires_at > timezone.now():
                continue
            locked.status = ApprovalStatus.EXPIRED
            locked.resolved_at = timezone.now()
            locked.save(update_fields=["status", "resolved_at", "updated_at"])
            _terminate_execution(
                locked, error_code="approval_expired", error_message="The approval request expired."
            )
            record_event(
                action=AuditAction.APPROVAL_EXPIRED,
                target_type="approval_request",
                target_id=locked.id,
                actor=None,
                workspace=locked.workspace,
                metadata={"approval_request_id": str(locked.id)},
            )
        count += 1
    return count


def cancel_approval_for_execution(
    *, execution: ToolExecution, reason: str = "run_cancelled"
) -> None:
    """Section 46: if the underlying run/execution is cancelled while an
    approval is pending, the approval becomes non-actionable."""
    approval = ApprovalRequest.objects.filter(tool_execution=execution).select_for_update().first()
    if approval is None or approval.status != ApprovalStatus.PENDING:
        return
    with transaction.atomic():
        approval.status = ApprovalStatus.CANCELLED
        approval.resolved_at = timezone.now()
        approval.save(update_fields=["status", "resolved_at", "updated_at"])
        record_event(
            action=AuditAction.APPROVAL_CANCELLED,
            target_type="approval_request",
            target_id=approval.id,
            actor=None,
            workspace=approval.workspace,
            metadata={"approval_request_id": str(approval.id), "reason": reason},
        )


def _terminate_execution(approval: ApprovalRequest, *, error_code: str, error_message: str) -> None:
    ToolExecution.objects.filter(
        pk=approval.tool_execution_id, status=ToolExecutionStatus.WAITING_FOR_APPROVAL
    ).update(
        status=ToolExecutionStatus.APPROVAL_TERMINATED,
        error_code=error_code,
        error_message_safe=error_message,
        completed_at=timezone.now(),
        updated_at=timezone.now(),
    )


def _dispatch_resume(approval_id: uuid.UUID) -> None:
    from .tasks import resume_approved_action_task

    resume_approved_action_task.delay(str(approval_id))
