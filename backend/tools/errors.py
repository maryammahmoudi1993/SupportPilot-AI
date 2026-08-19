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
