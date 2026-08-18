"""Stable, safe agent-domain failures (distinct from provider errors)."""


class AgentError(Exception):
    code = "agent_error"
    safe_message = "The agent request could not be completed."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.safe_message)


class AgentVersionNotPublishableError(AgentError):
    code = "agent_version_not_publishable"
    safe_message = "Only a draft version can be published."


class AgentVersionImmutableError(AgentError):
    code = "agent_version_immutable"
    safe_message = "A published or retired version cannot be modified."


class AgentVersionNotPublishedError(AgentError):
    code = "agent_version_not_published"
    safe_message = "Runs can only be started against a published agent version."


class AgentRunInvalidTransitionError(AgentError):
    code = "agent_run_invalid_transition"
    safe_message = "The run is not in a state that supports this action."


class AgentRunNotCancellableError(AgentError):
    code = "agent_run_not_cancellable"
    safe_message = "This run can no longer be cancelled."
