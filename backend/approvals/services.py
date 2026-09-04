"""Approval lifecycle services (Phase 8; webhook events added Phase 10
Block 3).

``create_or_reuse_approval_request`` is called only from the tool-execution
policy gate (``tools/execution.py``). Every other function here is called
from the approvals API/Celery task layer. Every state transition re-reads
the row under ``select_for_update`` inside a transaction before writing —
the same pattern ``agents/services.py`` and ``tools/execution.py`` already
use — which is what makes concurrent approve/reject/expire/cancel races
safe (section 41-42, 90-93).

Each lifecycle transition also emits a webhook event (Phase 10 Block 3,
section 47) with only already-safe, already-external-facing fields —
never a decision's private comment (section 9, 48), the redacted tool
arguments, or policy reasoning text.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from functools import partial
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import User
from audit.models import AuditAction
from audit.services import record_event
from common.redaction import redact
from tools.models import ToolExecution, ToolExecutionStatus
from webhooks.models import WebhookEventType
from webhooks.services import emit_event
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


def _schedule_approval_decision_observation(approval: ApprovalRequest, *, outcome: str) -> None:
    """Phase 11 Block 3 (section 24-26, 35-37): the single place every
    ApprovalRequest terminal-transition metric is recorded from —
    ``decide_approval`` (approved/rejected), ``_expire_if_stale``/
    ``expire_stale_approvals`` (expired), and
    ``cancel_approval_for_execution`` (cancelled). Every call site already
    guards its own single-fire DB transition (``select_for_update`` + a
    status check, or the idempotent-replay branch in ``decide_approval``
    that never reaches this at all), so this is never called twice for the
    same request. Recorded via ``transaction.on_commit``, matching every
    other domain metric here."""
    wait_duration_seconds = (
        (approval.resolved_at - approval.created_at).total_seconds()
        if approval.resolved_at is not None
        else None
    )
    if wait_duration_seconds is None:  # pragma: no cover - defensive, every caller sets it first
        return

    def _record() -> None:
        from observability.metrics import observe_approval_decision

        try:
            observe_approval_decision(outcome=outcome, wait_duration_seconds=wait_duration_seconds)
        except Exception:  # noqa: BLE001 - telemetry must fail open
            import logging

            logging.getLogger("supportpilot").warning(
                "approval_metrics_recording_failed",
                extra={"event": "metrics_error", "approval_request_id": str(approval.id)},
            )

    transaction.on_commit(_record)


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
        # Phase 10 Block 3, section 47: only safe, already-external-facing
        # fields — never the raw tool arguments, policy reasoning, or any
        # approver comment (section 9, 48; there is none yet at this point
        # anyway).
        emit_event(
            workspace=execution.workspace,
            event_type=WebhookEventType.APPROVAL_REQUESTED,
            data={
                "approval_id": str(approval.id),
                "tool_key": tool.spec.key,
                "risk_level": risk_assessment.effective_risk,
                "required_role": required_role,
                "summary": summary,
                "expires_at": approval.expires_at.isoformat(),
            },
        )

        def _record_created() -> None:
            from observability.metrics import observe_approval_request_created

            try:
                observe_approval_request_created()
            except Exception:  # noqa: BLE001 - telemetry must fail open
                import logging

                logging.getLogger("supportpilot").warning(
                    "approval_metrics_recording_failed",
                    extra={"event": "metrics_error", "approval_request_id": str(approval.id)},
                )

        transaction.on_commit(_record_created)
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
    # Deliberately no exception is raised from inside the ``atomic()`` block
    # below, mirroring the same fix applied to the Phase 8 tool-execution
    # gate (tools/execution.py::_run_policy_gate): Django rolls back the
    # whole block the moment any exception propagates out of it, which would
    # silently discard an expiry transition (or a decision) the instant
    # before reporting it. Every branch sets ``pending_error`` (or returns
    # normally) and the block commits; the control-flow exception is raised
    # only after that commit has already happened.
    pending_error: Exception | None = None
    with transaction.atomic():
        locked = ApprovalRequest.objects.select_for_update().get(pk=approval_request.pk)

        if _expire_if_stale(locked):
            pending_error = ApprovalExpiredError()
        elif locked.status == ApprovalStatus.EXPIRED:
            # Phase 16 Part A, section 9: the row was already expired by a
            # concurrent call (a racing decide_approval that won the lock
            # first, or the periodic sweeper) between this call reading its
            # argument and acquiring the lock above. ``_expire_if_stale``
            # only detects expiry it performs itself — without this branch,
            # an already-EXPIRED, non-PENDING row would fall through to the
            # PENDING-only branch below and record a phantom decision (a
            # false "approved"/"rejected" audit event and webhook, with no
            # actual execution ever resuming, since the underlying
            # ToolExecution was already terminated when the row first
            # expired).
            pending_error = ApprovalExpiredError()
        elif locked.status == ApprovalStatus.CANCELLED:
            pending_error = ApprovalCancelledError()
        elif locked.status in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED):
            resolved_value = (
                ApprovalDecisionValue.APPROVE
                if locked.status == ApprovalStatus.APPROVED
                else ApprovalDecisionValue.REJECT
            )
            if resolved_value != decision:
                pending_error = ApprovalAlreadyResolvedError()
            # else: idempotent replay (section 42) — fall through and
            # return the already-resolved row below, no error.
        else:
            # status == PENDING — current DB membership is authoritative,
            # never a cached/stale role (section 50).
            if locked.requested_by_id and locked.requested_by_id == actor.id:
                pending_error = ApprovalSelfApprovalForbiddenError()
            elif not role_satisfies_requirement(
                actor_role=actor_role, required_role=locked.required_role
            ):
                pending_error = ApprovalPermissionDeniedError()
            else:
                try:
                    with transaction.atomic():
                        ApprovalDecision.objects.create(
                            approval_request=locked,
                            decision=decision,
                            decided_by=actor,
                            safe_comment=comment[:1000],
                        )
                except IntegrityError:
                    # Lost a concurrent race for the one-decision-per-request
                    # slot (section 41, 90-91) — the winning decision is
                    # authoritative.
                    locked.refresh_from_db()
                    pending_error = ApprovalAlreadyResolvedError()

                if pending_error is None:
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
                    emit_event(
                        workspace=workspace,
                        event_type=(
                            WebhookEventType.APPROVAL_APPROVED
                            if decision == ApprovalDecisionValue.APPROVE
                            else WebhookEventType.APPROVAL_REJECTED
                        ),
                        data={
                            "approval_id": str(locked.id),
                            "required_role": locked.required_role,
                            "decided_at": locked.resolved_at.isoformat(),
                        },
                    )
                    if decision == ApprovalDecisionValue.REJECT:
                        _terminate_execution(
                            locked,
                            error_code="approval_rejected",
                            error_message="This action was rejected.",
                        )
                    _schedule_approval_decision_observation(
                        locked,
                        outcome=(
                            "approved" if decision == ApprovalDecisionValue.APPROVE else "rejected"
                        ),
                    )
                    # Section 41-45: a decision (approve *or* reject) always
                    # dispatches the same bounded resume continuation — the
                    # continuation service itself branches on the approval's
                    # now-persisted status to either execute the frozen
                    # action or hand the LLM a safe rejection outcome. This
                    # is what keeps "no business execution on reject" and
                    # "the run still reaches a final customer response"
                    # both true without a second dispatch mechanism.
                    transaction.on_commit(lambda: _dispatch_resume(locked.id))
    # transaction.atomic() committed here — safe to raise now.
    if pending_error is not None:
        raise pending_error
    return locked


def _expire_if_stale(locked: ApprovalRequest) -> bool:
    """Section 44: expiry is checked from the wall clock, never trusted from
    stale ``status`` alone. Returns ``True`` (and performs the transition)
    if this call just discovered the request is expired."""
    if locked.status != ApprovalStatus.PENDING:
        return False
    if timezone.now() < locked.expires_at:
        return False
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
    _emit_expired_event(locked)
    _schedule_approval_decision_observation(locked, outcome="expired")
    # Section 46-49: expiry never leaves the run waiting indefinitely — the
    # same bounded resume continuation used for reject dispatches here too,
    # never an LLM call inside this transaction (section 48).
    transaction.on_commit(lambda: _dispatch_resume(locked.id))
    return True


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
            _emit_expired_event(locked)
            _schedule_approval_decision_observation(locked, outcome="expired")
            # Section 48-49: dispatched per-row, after this row's own commit
            # — never inside a shared transaction spanning the whole sweep,
            # so one stuck/slow continuation can never block another row's
            # expiry transition, and a duplicate sweep delivery only ever
            # finds an already-EXPIRED row (the ``status != PENDING`` guard
            # above) and dispatches nothing a second time.
            transaction.on_commit(partial(_dispatch_resume, locked.id))
        count += 1
    return count


def cancel_approval_for_execution(
    *, execution: ToolExecution, reason: str = "run_cancelled"
) -> None:
    """Section 46: if the underlying run/execution is cancelled while an
    approval is pending, the approval becomes non-actionable."""
    with transaction.atomic():
        approval = (
            ApprovalRequest.objects.filter(tool_execution=execution).select_for_update().first()
        )
        if approval is None or approval.status != ApprovalStatus.PENDING:
            return
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
        _schedule_approval_decision_observation(approval, outcome="cancelled")


def _terminate_execution(approval: ApprovalRequest, *, error_code: str, error_message: str) -> None:
    updated = ToolExecution.objects.filter(
        pk=approval.tool_execution_id, status=ToolExecutionStatus.WAITING_FOR_APPROVAL
    ).update(
        status=ToolExecutionStatus.APPROVAL_TERMINATED,
        error_code=error_code,
        error_message_safe=error_message,
        completed_at=timezone.now(),
        updated_at=timezone.now(),
    )
    if updated:
        # Phase 11 Block 3 (section 19-20): the ``approval_terminated``
        # ToolExecution outcome — a plain queryset ``.update()``, not one of
        # ``tools/execution.py``'s own locked-transition functions, so it
        # is recorded here instead. ``updated`` (the row-count the ``UPDATE``
        # actually touched) is this call's own single-fire guard, mirroring
        # the ``select_for_update`` + status-check guard every other
        # terminal transition uses.
        transaction.on_commit(
            lambda: _schedule_tool_execution_metric(approval.tool_execution_id, error_code)
        )


def _schedule_tool_execution_metric(tool_execution_id, error_code: str) -> None:
    from observability.metrics import observe_tool_execution

    try:
        execution = ToolExecution.objects.select_related("tool_definition").get(
            pk=tool_execution_id
        )
        duration_seconds = (
            (execution.completed_at - execution.started_at).total_seconds()
            if execution.started_at is not None and execution.completed_at is not None
            else None
        )
        observe_tool_execution(
            tool_name=execution.tool_definition.key,
            outcome="approval_terminated",
            duration_seconds=duration_seconds,
        )
    except Exception:  # noqa: BLE001 - telemetry must fail open
        import logging

        logging.getLogger("supportpilot").warning(
            "tool_execution_metrics_recording_failed",
            extra={"event": "metrics_error", "tool_execution_id": str(tool_execution_id)},
        )


def _emit_expired_event(locked: ApprovalRequest) -> None:
    # Always set by the caller immediately before this (both call sites)
    # — never actually None here, just nullable at the model level for
    # every *other* (non-resolved) lifecycle state.
    assert locked.resolved_at is not None
    emit_event(
        workspace=locked.workspace,
        event_type=WebhookEventType.APPROVAL_EXPIRED,
        data={
            "approval_id": str(locked.id),
            "required_role": locked.required_role,
            "expired_at": locked.resolved_at.isoformat(),
        },
    )


def _dispatch_resume(approval_id: uuid.UUID) -> None:
    from common.correlation import get_correlation_id

    from .tasks import resume_approved_action_task

    resume_approved_action_task.delay(str(approval_id), correlation_id=get_correlation_id())
