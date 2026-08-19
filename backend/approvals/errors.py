"""Stable, safe approval-domain error taxonomy (section 72-73)."""

from __future__ import annotations


class ApprovalError(Exception):
    code = "approval_error"
    safe_message = "The approval request could not be processed."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.safe_message)
        if message:
            self.safe_message = message


class ApprovalRequiredError(ApprovalError):
    """Raised by the tool-execution gate itself: the action was routed to a
    (new or already-pending) ApprovalRequest and the handler was never
    invoked (section 61)."""

    code = "approval_required"
    safe_message = "This action requires human approval before it can execute."


class ApprovalNotFoundError(ApprovalError):
    code = "approval_not_found"
    safe_message = "Approval request not found."


class ApprovalAlreadyResolvedError(ApprovalError):
    code = "approval_already_resolved"
    safe_message = "This approval request has already been resolved."


class ApprovalExpiredError(ApprovalError):
    code = "approval_expired"
    safe_message = "This approval request has expired."


class ApprovalCancelledError(ApprovalError):
    code = "approval_cancelled"
    safe_message = "This approval request was cancelled."


class ApprovalRejectedError(ApprovalError):
    code = "approval_rejected"
    safe_message = "This action was rejected by an approver."


class ApprovalPermissionDeniedError(ApprovalError):
    code = "approval_permission_denied"
    safe_message = "You do not have permission to decide this approval request."


class ApprovalSelfApprovalForbiddenError(ApprovalError):
    code = "approval_self_approval_forbidden"
    safe_message = "You cannot approve or reject a request you initiated."


class ApprovalActionChangedError(ApprovalError):
    code = "approval_action_changed"
    safe_message = "The proposed action no longer matches what was approved."


class ApprovalResumeConflictError(ApprovalError):
    code = "approval_resume_conflict"
    safe_message = "This approved action has already been resumed."
