"""Stable, safe tool-domain error taxonomy (section 49 of the Phase 6 brief).

Every code here is safe to persist, log, and return to a caller. Messages
are deliberately generic — never a Python repr, traceback, or vendor
payload. See ``ToolExecution.error_message_safe``.
"""

from __future__ import annotations


class ToolError(Exception):
    code = "tool_error"
    safe_message = "The tool request could not be completed."
    retryable = False

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.safe_message)
        if message:
            self.safe_message = message


class ToolNotRegisteredError(ToolError):
    code = "tool_not_registered"
    safe_message = "The requested tool is not registered."


class ToolNotBoundError(ToolError):
    code = "tool_not_bound"
    safe_message = "This agent version is not bound to the requested tool."


class ToolDisabledError(ToolError):
    code = "tool_disabled"
    safe_message = "The requested tool is currently disabled."


class ToolInvalidInputError(ToolError):
    code = "tool_invalid_input"
    safe_message = "The tool arguments failed validation."


class ToolInvalidOutputError(ToolError):
    code = "tool_invalid_output"
    safe_message = "The tool produced an invalid result."


class ToolTimeoutError(ToolError):
    code = "tool_timeout"
    safe_message = "The tool did not complete within its allotted time."


class ToolExecutionFailedError(ToolError):
    code = "tool_execution_failed"
    safe_message = "The tool failed to execute."


class ToolRetryExhaustedError(ToolError):
    code = "tool_retry_exhausted"
    safe_message = "The tool failed after exhausting its retry budget."


class ToolIdempotencyConflictError(ToolError):
    code = "tool_idempotency_conflict"
    safe_message = "This idempotency key was already used with different arguments."


class ToolExecutionInProgressError(ToolError):
    code = "tool_execution_in_progress"
    safe_message = "A matching tool execution is already in progress."


class ToolBudgetExceededError(ToolError):
    code = "tool_budget_exceeded"
    safe_message = "The run's tool-call budget has been exhausted."


class ToolPermissionDeniedError(ToolError):
    code = "tool_permission_denied"
    safe_message = "You do not have permission to use this tool."


class ToolConfigurationError(ToolError):
    code = "tool_configuration_error"
    safe_message = "The tool is misconfigured."


class ToolRunNotExecutableError(ToolError):
    code = "tool_run_not_executable"
    safe_message = "The agent run is not in a state that allows tool execution."


# ---------------------------------------------------------------------------
# Phase 8: the deterministic policy gate's outcomes, bridged into the same
# ToolError taxonomy the rest of execute_tool already raises. Model output is
# never authorization — every one of these is raised by server-owned code in
# tools/execution.py, never by a tool handler.
# ---------------------------------------------------------------------------


class ToolPolicyDeniedError(ToolError):
    code = "policy_action_denied"
    safe_message = "This action is denied by workspace policy."


class ToolPolicyEvaluationFailedError(ToolError):
    code = "policy_evaluation_failed"
    safe_message = "The action could not be safely evaluated against workspace policy."


class ToolApprovalRequiredError(ToolError):
    code = "approval_required"
    safe_message = "This action requires human approval before it can execute."


class ToolApprovalRejectedError(ToolError):
    code = "approval_rejected"
    safe_message = "This action was rejected by an approver."


class ToolApprovalExpiredError(ToolError):
    code = "approval_expired"
    safe_message = "The approval request for this action expired before it was decided."


class ToolApprovalCancelledError(ToolError):
    code = "approval_cancelled"
    safe_message = "The approval request for this action was cancelled."
