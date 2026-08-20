"""Stable, safe policy-domain error taxonomy (section 72-73 of the Phase 8
brief). Every code here is safe to persist, log, and return to a caller —
never a Python repr, traceback, or predicate implementation detail."""

from __future__ import annotations


class PolicyError(Exception):
    code = "policy_error"
    safe_message = "The policy could not be evaluated."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.safe_message)
        if message:
            self.safe_message = message


class PolicyNotConfiguredError(PolicyError):
    code = "policy_not_configured"
    safe_message = "No workspace policy is configured; the system default applies."


class PolicyEvaluationFailedError(PolicyError):
    """Raised for any condition that would otherwise force a guess (unknown
    predicate, malformed condition config, corrupt rule). The evaluator
    always fails closed (section 27) — this error is mapped to a safe DENY,
    never to ALLOW."""

    code = "policy_evaluation_failed"
    safe_message = "The action could not be safely evaluated against workspace policy."


class PolicyActionDeniedError(PolicyError):
    code = "policy_action_denied"
    safe_message = "This action is denied by workspace policy."


class PolicyInvalidRuleError(PolicyError):
    code = "policy_invalid_rule"
    safe_message = "The policy rule configuration is invalid."


class PolicyVersionNotActivatableError(PolicyError):
    code = "policy_version_not_activatable"
    safe_message = "This policy version cannot be activated in its current state."


class PolicyLimitExceededError(PolicyError):
    code = "policy_limit_exceeded"
    safe_message = "This policy configuration exceeds a configured limit."
