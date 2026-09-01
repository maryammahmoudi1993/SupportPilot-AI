"""Stable, safe evaluation-domain failures."""


class EvaluationError(Exception):
    code = "evaluation_error"
    safe_message = "The evaluation request could not be completed."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.safe_message)


class EvaluationDatasetHasNoActiveCasesError(EvaluationError):
    code = "evaluation_dataset_no_active_cases"
    safe_message = "The dataset has no active cases to run."


class EvaluationAgentVersionNotPublishedError(EvaluationError):
    code = "evaluation_agent_version_not_published"
    safe_message = "Evaluation runs can only target a published agent version."


class EvaluationRunNotCancellableError(EvaluationError):
    code = "evaluation_run_not_cancellable"
    safe_message = "This evaluation run can no longer be cancelled."


class EvaluationResultNotReplayableError(EvaluationError):
    code = "evaluation_result_not_replayable"
    safe_message = "This result is not in a state that supports replay."


class EvaluationRunsNotComparableError(EvaluationError):
    code = "evaluation_runs_not_comparable"
    safe_message = "These runs are not comparable — they were evaluated over incompatible cases."


class EvaluationLiveProviderNotAllowedError(EvaluationError):
    code = "evaluation_live_provider_not_allowed"
    safe_message = "Evaluation cannot run while live external providers are enabled."
