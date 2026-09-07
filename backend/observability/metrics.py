"""Central, bounded-cardinality metrics registry (Phase 11 Block 1).

Every metric defined anywhere in this application is declared exactly once,
in this module — never ad hoc inside a view, service, or task — so that
names, label sets, and cardinality can be reviewed in one place (section 7).

Cardinality is a release-critical property, not a style preference (section
8): a metric label populated from an unbounded value (a workspace/customer/
delivery/request id, a raw URL, an exception message, a provider response
body) turns one time series into an unbounded number of them, which is a
real production outage vector for any metrics backend. Every label used
anywhere in this module is drawn from a small, server-owned, bounded set —
see each metric's docstring for its exact allowed values.

Multiprocess correctness (section 29): production runs multiple Gunicorn
worker processes and separate Celery worker processes. ``prometheus_client``
decides, at metric *construction* time (i.e. at module import time, once per
process), whether to use its multiprocess-safe value class — purely by
checking whether ``PROMETHEUS_MULTIPROC_DIR`` is present in the environment.
This means that env var must already be set, pointing at an existing,
per-deployment-fresh directory, before this module is first imported —
before Gunicorn forks its workers. Each process then writes its samples to
per-process mmap files under that directory rather than sharing one
in-memory registry. Rendering a scrape (``render_metrics`` below) is what
differs from single-process mode: it builds a *fresh* ``CollectorRegistry``
wired to a ``MultiProcessCollector`` that reads and aggregates every
process's mmap files at scrape time, instead of reading process-local memory
directly. See ``docs/architecture/observability.md`` for the full
explanation and ``config/gunicorn_conf.py`` for the required
worker-lifecycle cleanup hook.
"""

from __future__ import annotations

import logging
import os

from prometheus_client import CONTENT_TYPE_LATEST as METRICS_CONTENT_TYPE
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)

logger = logging.getLogger("supportpilot")

__all__ = [
    "METRIC_NAMESPACE",
    "METRICS_CONTENT_TYPE",
    "HTTP_REQUESTS_TOTAL",
    "HTTP_REQUEST_DURATION_SECONDS",
    "CELERY_TASKS_TOTAL",
    "CELERY_TASK_DURATION_SECONDS",
    "observe_http_request",
    "observe_celery_task",
    "AGENT_RUNS_TOTAL",
    "AGENT_RUN_DURATION_SECONDS",
    "LLM_REQUESTS_TOTAL",
    "LLM_REQUEST_DURATION_SECONDS",
    "LLM_TOKENS_TOTAL",
    "TOOL_EXECUTIONS_TOTAL",
    "TOOL_EXECUTION_DURATION_SECONDS",
    "POLICY_DECISIONS_TOTAL",
    "APPROVAL_REQUESTS_TOTAL",
    "APPROVAL_DECISIONS_TOTAL",
    "APPROVAL_WAIT_DURATION_SECONDS",
    "HANDOFFS_TOTAL",
    "HANDOFF_DURATION_SECONDS",
    "observe_agent_run_terminal",
    "observe_llm_request",
    "observe_tool_execution",
    "observe_policy_decision",
    "observe_approval_request_created",
    "observe_approval_decision",
    "observe_handoff_created",
    "observe_handoff_terminal",
    "DELIVERIES_CREATED_TOTAL",
    "DELIVERY_ATTEMPTS_TOTAL",
    "DELIVERY_ATTEMPT_DURATION_SECONDS",
    "DELIVERY_ATTEMPT_FAILURES_TOTAL",
    "DELIVERY_RETRIES_TOTAL",
    "DELIVERY_TERMINAL_TOTAL",
    "DELIVERY_END_TO_END_DURATION_SECONDS",
    "DELIVERY_CLAIM_RECOVERIES_TOTAL",
    "DELIVERY_BROKER_PUBLICATION_FAILURES_TOTAL",
    "DELIVERY_REDRIVES_TOTAL",
    "WEBHOOK_RESPONSES_TOTAL",
    "WEBHOOK_DESTINATION_REJECTIONS_TOTAL",
    "DELIVERY_DUE_COUNT",
    "DELIVERY_EXPIRED_CLAIM_COUNT",
    "DELIVERY_OLDEST_DUE_AGE_SECONDS",
    "observe_delivery_created",
    "observe_delivery_attempt_claimed",
    "observe_delivery_attempt_outcome",
    "observe_delivery_retry_scheduled",
    "observe_delivery_terminal",
    "observe_delivery_claim_recovery",
    "observe_delivery_broker_publication_failure",
    "observe_delivery_redrive",
    "observe_webhook_response",
    "observe_webhook_destination_rejection",
    "observe_stuck_run_recovery",
    "refresh_delivery_backlog_gauges",
    "render_metrics",
]

METRIC_NAMESPACE = "supportpilot"

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

#: Labels: ``method`` (one of ``GET``/``POST``/``PUT``/``PATCH``/``DELETE``/
#: ``HEAD``/``OPTIONS``/``OTHER``), ``route`` (the
#: resolved Django URL name, e.g. ``"webhook-endpoint-detail"`` — bounded by
#: the URLconf, never the raw request path/querystring; unresolved paths are
#: collapsed to the single value ``"unmatched"`` rather than one series per
#: probed path — see ``observability/middleware.py``), ``status_class``
#: (``"2xx"``/``"3xx"``/``"4xx"``/``"5xx"``/``"other"`` — 5 values).
HTTP_REQUESTS_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_http_requests_total",
    "Total HTTP requests handled, by method/route/status class.",
    ["method", "route", "status_class"],
)

#: Same bounded label set as ``HTTP_REQUESTS_TOTAL`` minus ``status_class``
#: (duration buckets already convey outcome-independent cost; keeping the
#: label set here smaller bounds bucket-count multiplication).
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    f"{METRIC_NAMESPACE}_http_request_duration_seconds",
    "HTTP request duration in seconds, by method/route.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)


_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
_HTTP_STATUS_CLASSES = frozenset({2, 3, 4, 5})


def _http_method(method: str) -> str:
    """Collapse attacker-controlled/custom HTTP verbs to one stable label."""
    normalized_method = method.upper()
    return normalized_method if normalized_method in _HTTP_METHODS else "OTHER"


def _status_class(status_code: int) -> str:
    """Return a bounded class even if application code emits an invalid status."""
    status_class = status_code // 100
    return f"{status_class}xx" if status_class in _HTTP_STATUS_CLASSES else "other"


def observe_http_request(
    *, method: str, route: str, status_code: int, duration_seconds: float
) -> None:
    """The single call site every HTTP metrics recorder must go through
    (section 7) — keeps the two HTTP metrics' label values consistent with
    each other by construction."""
    method_label = _http_method(method)
    status_class = _status_class(status_code)
    HTTP_REQUESTS_TOTAL.labels(method=method_label, route=route, status_class=status_class).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(method=method_label, route=route).observe(duration_seconds)


# ---------------------------------------------------------------------------
# Celery tasks (Phase 11 Block 2)
# ---------------------------------------------------------------------------
#
# Recorded from ``common.tasks.CorrelatedTask`` — every first-party
# ``@shared_task`` is defined with ``base=CorrelatedTask``, so this is the
# single call site for both metrics, exactly like ``observe_http_request``
# above.
#
# Deployment note: Celery workers deliberately run in ``prometheus_client``'s
# default single-process mode (see ``docs/architecture/observability.md``),
# so these metrics accumulate correctly in-process but are not yet exposed
# for scraping from a worker — that requires a worker-process-safe HTTP
# exposition strategy (multiple prefork children cannot share one port) and
# is left to a later block, matching the operational gap ADR 0009 already
# flagged. Until then these metrics are directly assertable in tests and
# ready for that later block to expose, not yet scrapeable in production.

#: Labels: ``task_name`` (the Celery task's registered name — bounded
#: because it is drawn from this codebase's own ``@shared_task``
#: definitions, never from task input), ``outcome`` (``"success"`` /
#: ``"failure"`` / ``"retry"`` — 3 values).
CELERY_TASKS_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_celery_tasks_total",
    "Total Celery tasks executed, by task name and outcome.",
    ["task_name", "outcome"],
)

#: Same bounded label set as ``HTTP_REQUEST_DURATION_SECONDS``'s ``route``:
#: ``task_name`` only — outcome-independent cost, keeping bucket-count
#: multiplication bounded.
CELERY_TASK_DURATION_SECONDS = Histogram(
    f"{METRIC_NAMESPACE}_celery_task_duration_seconds",
    "Celery task execution duration in seconds, by task name.",
    ["task_name"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 300),
)

_CELERY_OUTCOMES = frozenset({"success", "failure", "retry"})


def observe_celery_task(*, task_name: str, outcome: str, duration_seconds: float) -> None:
    """The single call site every Celery metrics recorder must go through
    (mirrors ``observe_http_request`` above)."""
    outcome_label = outcome if outcome in _CELERY_OUTCOMES else "failure"
    CELERY_TASKS_TOTAL.labels(task_name=task_name, outcome=outcome_label).inc()
    CELERY_TASK_DURATION_SECONDS.labels(task_name=task_name).observe(duration_seconds)


# ---------------------------------------------------------------------------
# Agent / LLM / tool / policy / approval / handoff domain metrics
# (Phase 11 Block 3)
#
# Every metric here represents an authoritative, already-committed business
# state transition — never an HTTP call, never a raw retry attempt (section
# 2: "metrics must represent business operations, not merely HTTP calls").
# Each ``observe_*`` function below is the single call site its domain
# boundary goes through (mirroring ``observe_http_request``/
# ``observe_celery_task`` above); see the call sites themselves
# (agents/services.py, agents/runtime/graph.py, tools/execution.py,
# approvals/services.py, tickets/services.py) for exactly where and why.
#
# Cardinality (section 31): every label below is drawn from a small,
# code-owned enum — never an id, a user-facing name, a raw error message, or
# any other unbounded value. An unrecognized/attacker-influenced value never
# reaches Prometheus as a new label value — each ``observe_*`` function
# collapses anything outside its bounded set to a fixed fallback, exactly
# like ``_http_method``/``_status_class`` above.
# ---------------------------------------------------------------------------

# --- Agent runs --------------------------------------------------------

#: Labels: ``trigger`` (``AgentRunTrigger`` — manual/conversation/ticket/api/
#: evaluation, 5 values, code-owned), ``outcome`` (one of ``AGENT_RUN_TERMINAL_STATUSES``
#: — succeeded/failed/cancelled/budget_exceeded/handed_off, 5 values).
#: ``WAITING_FOR_APPROVAL`` is deliberately never observed here — it is not
#: terminal (section 13); ``HANDED_OFF`` is a successful escalation outcome,
#: never collapsed into "failed" (section 13, 28).
AGENT_RUNS_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_agent_runs_total",
    "Total AgentRun terminal transitions, by trigger and outcome.",
    ["trigger", "outcome"],
)

#: End-to-end duration (``created_at`` -> the terminal timestamp) — labeled
#: only by ``trigger``. Named/documented as end-to-end, not "active compute
#: time" (section 14): a run that spent time WAITING_FOR_APPROVAL includes
#: that human wait in this duration, because ``AgentRun`` has no separate
#: "compute-only" timestamp to derive a narrower measure from. Buckets
#: reflect that this can span from a fast single-turn reply to a multi-turn
#: run with tool calls and RAG retrieval — not HTTP-request-latency buckets
#: (section 44).
AGENT_RUN_DURATION_SECONDS = Histogram(
    f"{METRIC_NAMESPACE}_agent_run_duration_seconds",
    "AgentRun end-to-end duration in seconds (created_at to terminal), by trigger.",
    ["trigger"],
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300, 600),
)

_AGENT_RUN_TRIGGERS = frozenset({"manual", "conversation", "ticket", "api", "evaluation"})
_AGENT_RUN_OUTCOMES = frozenset(
    {"succeeded", "failed", "cancelled", "budget_exceeded", "handed_off"}
)


def observe_agent_run_terminal(
    *, trigger: str, outcome: str, duration_seconds: float | None
) -> None:
    """The single call site every AgentRun terminal-transition recorder
    must go through (``agents/services.py``'s ``_complete_run``,
    ``_fail_run``, ``_budget_exceeded_run``, ``_complete_run_as_handoff``).
    Callers are responsible for calling this at most once per genuine
    transition (section 35: each of those functions already guards its own
    single-fire DB transition with ``select_for_update`` + a status check —
    the same guard that prevents this from double-counting)."""
    trigger_label = trigger if trigger in _AGENT_RUN_TRIGGERS else "manual"
    outcome_label = outcome if outcome in _AGENT_RUN_OUTCOMES else "failed"
    AGENT_RUNS_TOTAL.labels(trigger=trigger_label, outcome=outcome_label).inc()
    if duration_seconds is not None:
        AGENT_RUN_DURATION_SECONDS.labels(trigger=trigger_label).observe(duration_seconds)


# --- LLM provider calls -------------------------------------------------

#: Labels: ``provider`` (the adapter's own ``name`` — a small, code-owned
#: set today: ``fake``/``openai``; unrecognized values collapse to
#: ``other``, defense-in-depth against a future adapter forgetting to
#: register itself here), ``outcome`` (``success`` or a
#: ``agents.providers.errors.ProviderError`` subclass's own ``code`` — a
#: small, code-owned, closed taxonomy; never derived from the provider's raw
#: response). Deliberately no ``model`` label — ``AgentVersion.model`` is a
#: free-text field an operator can set to anything (section 16-17: only
#: bounded, server-owned values may become labels).
LLM_REQUESTS_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_llm_requests_total",
    "Total LLM provider calls, by provider and outcome.",
    ["provider", "outcome"],
)

#: Same bounded label set convention as ``HTTP_REQUEST_DURATION_SECONDS``:
#: ``provider`` only. Buckets reflect real LLM call latency, not HTTP
#: request latency (section 44) — noticeably heavier-tailed.
LLM_REQUEST_DURATION_SECONDS = Histogram(
    f"{METRIC_NAMESPACE}_llm_request_duration_seconds",
    "LLM provider call duration in seconds, by provider.",
    ["provider"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60),
)

#: Labels: ``provider``, ``token_type`` (``input``/``output`` — 2 values).
#: Only observed when the provider actually returned usage figures
#: (``LLMResponse.usage`` — every adapter, including the fake one, always
#: populates this; section 17 forbids estimating/fabricating token counts
#: when a provider does not).
LLM_TOKENS_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_llm_tokens_total",
    "Total tokens reported by the LLM provider, by provider and token type.",
    ["provider", "token_type"],
)

_LLM_PROVIDERS = frozenset({"fake", "openai"})
_LLM_OUTCOMES = frozenset(
    {
        "success",
        "provider_authentication_failed",
        "provider_rate_limited",
        "provider_timeout",
        "provider_temporarily_unavailable",
        "provider_invalid_request",
        "provider_malformed_response",
        "provider_content_rejected",
        "provider_configuration_error",
        "provider_unknown_error",
    }
)


def observe_llm_request(
    *,
    provider: str,
    outcome: str,
    duration_seconds: float,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> None:
    """The single call site every LLM provider call recorder must go
    through (``agents/runtime/graph.py``'s ``_generate_response`` node —
    the one place ``LLMProvider.generate`` is ever called)."""
    provider_label = provider if provider in _LLM_PROVIDERS else "other"
    outcome_label = outcome if outcome in _LLM_OUTCOMES else "provider_unknown_error"
    LLM_REQUESTS_TOTAL.labels(provider=provider_label, outcome=outcome_label).inc()
    LLM_REQUEST_DURATION_SECONDS.labels(provider=provider_label).observe(duration_seconds)
    if input_tokens is not None:
        LLM_TOKENS_TOTAL.labels(provider=provider_label, token_type="input").inc(input_tokens)
    if output_tokens is not None:
        LLM_TOKENS_TOTAL.labels(provider=provider_label, token_type="output").inc(output_tokens)


# --- Tool executions ------------------------------------------------------

#: Labels: ``tool_name`` (the tool's registered ``key`` — bounded because it
#: is drawn from ``tools.registry``, a code-owned catalog, never from
#: arbitrary model/tool-call input; section 19), ``outcome`` (one of
#: ``TOOL_EXECUTION_TERMINAL_STATUSES`` — succeeded/failed/timed_out/
#: cancelled/blocked_by_policy/approval_terminated, 6 values — the actual
#: ``ToolExecutionStatus`` terminal set, not an invented taxonomy; section
#: 20).
TOOL_EXECUTIONS_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_tool_executions_total",
    "Total ToolExecution terminal transitions, by tool name and outcome.",
    ["tool_name", "outcome"],
)

TOOL_EXECUTION_DURATION_SECONDS = Histogram(
    f"{METRIC_NAMESPACE}_tool_execution_duration_seconds",
    "ToolExecution duration in seconds (started_at to completed_at), by tool name.",
    ["tool_name"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)

_TOOL_EXECUTION_OUTCOMES = frozenset(
    {
        "succeeded",
        "failed",
        "timed_out",
        "cancelled",
        "blocked_by_policy",
        "approval_terminated",
    }
)


def observe_tool_execution(*, tool_name: str, outcome: str, duration_seconds: float | None) -> None:
    """The single call site every ToolExecution terminal-transition
    recorder must go through (``tools/execution.py``'s ``_finalize_success``,
    ``_finalize_failure``, ``_transition_blocked_by_policy``, and
    ``approvals/services.py``'s ``_terminate_execution`` for the
    ``approval_terminated`` outcome). ``tool_name`` is trusted bounded input
    from the code-owned tool registry — still collapsed to ``"unknown"`` if
    ever missing/empty, never left to create an unbounded label from a
    caller bug."""
    tool_label = tool_name or "unknown"
    outcome_label = outcome if outcome in _TOOL_EXECUTION_OUTCOMES else "failed"
    TOOL_EXECUTIONS_TOTAL.labels(tool_name=tool_label, outcome=outcome_label).inc()
    if duration_seconds is not None:
        TOOL_EXECUTION_DURATION_SECONDS.labels(tool_name=tool_label).observe(duration_seconds)


# --- Policy decisions -------------------------------------------------

#: Labels: ``decision`` (``PolicyEffect`` — allow/deny/require_approval, 3
#: values, code-owned). Deliberately no workspace/policy/user/tool label
#: (section 22) — those are all either unbounded or not provably
#: server-owned-and-small.
POLICY_DECISIONS_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_policy_decisions_total",
    "Total policy evaluation decisions, by decision.",
    ["decision"],
)

_POLICY_DECISIONS = frozenset({"allow", "deny", "require_approval"})


def observe_policy_decision(*, decision: str) -> None:
    """The single call site every policy-evaluation recorder must go
    through (``tools/execution.py``'s ``_run_policy_gate``, at the point
    its own ``outcome`` classification — allow/deny/require_approval — is
    already committed)."""
    decision_label = decision if decision in _POLICY_DECISIONS else "deny"
    POLICY_DECISIONS_TOTAL.labels(decision=decision_label).inc()


# --- Approvals ----------------------------------------------------------

#: Created-only counter — no labels (every created request is the same
#: bounded event; ``required_role``/``tool_key`` are not provably bounded
#: enough across a whole deployment's tool catalog + role set to justify a
#: label here, matching section 24's "do not label by ... unless provably
#: bounded").
APPROVAL_REQUESTS_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_approval_requests_total",
    "Total ApprovalRequest rows created.",
)

#: Labels: ``outcome`` (one of ``APPROVAL_TERMINAL_STATUSES`` —
#: approved/rejected/expired/cancelled, 4 values — the actual
#: ``ApprovalStatus`` terminal set).
APPROVAL_DECISIONS_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_approval_decisions_total",
    "Total ApprovalRequest terminal transitions, by outcome.",
    ["outcome"],
)

#: request creation -> terminal decision/expiry/cancel only (section 25) —
#: never observed for a still-PENDING request. Minutes-to-hours buckets
#: (section 44), not web-request-latency buckets: a human decision can
#: reasonably take anywhere from seconds to the request's own TTL, which is
#: configured in hours.
APPROVAL_WAIT_DURATION_SECONDS = Histogram(
    f"{METRIC_NAMESPACE}_approval_wait_duration_seconds",
    "ApprovalRequest wait duration in seconds (created_at to resolved_at), by outcome.",
    ["outcome"],
    buckets=(10, 30, 60, 300, 900, 1800, 3600, 7200, 21600, 86400),
)

_APPROVAL_OUTCOMES = frozenset({"approved", "rejected", "expired", "cancelled"})


def observe_approval_request_created() -> None:
    """The single call site for a newly-created ``ApprovalRequest``
    (``approvals/services.py``'s ``create_or_reuse_approval_request``, only
    on the genuinely-new-row branch — never the reused-existing-row early
    return, which would otherwise double-count section 35's "same
    idempotency key" case)."""
    APPROVAL_REQUESTS_TOTAL.inc()


def observe_approval_decision(*, outcome: str, wait_duration_seconds: float) -> None:
    """The single call site every ApprovalRequest terminal-transition
    recorder must go through (``approvals/services.py``'s
    ``decide_approval``, ``_expire_if_stale``, and
    ``cancel_approval_for_execution``) — each already guards its own
    single-fire DB transition, so this is never called twice for the same
    request (section 25: never observed for a still-pending request either
    — every call site already has both a resolved outcome and a
    ``resolved_at`` timestamp by the time it calls this)."""
    outcome_label = outcome if outcome in _APPROVAL_OUTCOMES else "expired"
    APPROVAL_DECISIONS_TOTAL.labels(outcome=outcome_label).inc()
    APPROVAL_WAIT_DURATION_SECONDS.labels(outcome=outcome_label).observe(wait_duration_seconds)


# --- Human handoffs -------------------------------------------------------

#: Labels: ``reason_code`` (``HumanHandoffReason`` — 5 values, code-owned).
HANDOFFS_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_handoffs_total",
    "Total HumanHandoff rows created, by reason code.",
    ["reason_code"],
)

#: created_at -> resolved_at only (never observed for cancelled — Phase 10's
#: ``HumanHandoff`` model has no meaningful "cancelled_at", and a cancelled
#: handoff was never actually worked, so a wait/duration figure for it would
#: be misleading, not merely incomplete; section 27-28 — a cancellation is
#: not a failure to fold into this measure at all). Human-workflow-scale
#: buckets, not web-request-latency buckets (section 44).
HANDOFF_DURATION_SECONDS = Histogram(
    f"{METRIC_NAMESPACE}_handoff_duration_seconds",
    "HumanHandoff duration in seconds (created_at to resolved_at) for resolved handoffs.",
    buckets=(60, 300, 900, 1800, 3600, 7200, 21600, 43200, 86400),
)

_HANDOFF_REASON_CODES = frozenset(
    {
        "customer_requested",
        "unsupported_action",
        "runtime_failure",
        "low_confidence",
        "policy_escalation",
    }
)


def observe_handoff_created(*, reason_code: str) -> None:
    """The single call site for a newly-created ``HumanHandoff``
    (``tickets/services.py``'s ``create_or_reuse_handoff``, only on the
    genuinely-new-row branch — mirrors ``observe_approval_request_created``'s
    reused-row exclusion)."""
    reason_label = reason_code if reason_code in _HANDOFF_REASON_CODES else "policy_escalation"
    HANDOFFS_TOTAL.labels(reason_code=reason_label).inc()


def observe_handoff_terminal(*, duration_seconds: float | None) -> None:
    """The single call site for a resolved ``HumanHandoff``
    (``tickets/services.py``'s ``resolve_handoff``) — cancellation
    deliberately never calls this (see ``HANDOFF_DURATION_SECONDS``'s
    docstring)."""
    if duration_seconds is not None:
        HANDOFF_DURATION_SECONDS.observe(duration_seconds)


# ---------------------------------------------------------------------------
# Evaluations (Phase 12) — every label is a small, bounded, code-owned enum
# value; never a dataset/case/run/agent-version/request/trace id, raw intent,
# or unbounded tool name (section 42 of the Phase 12 brief).
# ---------------------------------------------------------------------------

_EVALUATION_RUN_OUTCOMES = frozenset({"succeeded", "partial", "failed", "cancelled"})
_EVALUATION_CASE_OUTCOMES = frozenset({"passed", "failed", "execution_failed", "cancelled"})
_EVALUATION_REGRESSION_CATEGORIES = frozenset(
    {"pass_rate", "forbidden_tool", "approval_compliance", "policy_compliance", "handoff_rate"}
)

EVALUATION_RUNS_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_evaluation_runs_total",
    "Total EvaluationRun terminal transitions, by outcome.",
    ["outcome"],
)

EVALUATION_CASES_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_evaluation_cases_total",
    "Total EvaluationResult terminal transitions, by outcome.",
    ["outcome"],
)

EVALUATION_CASE_DURATION_SECONDS = Histogram(
    f"{METRIC_NAMESPACE}_evaluation_case_duration_seconds",
    "EvaluationResult execution duration in seconds, by outcome.",
    ["outcome"],
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300),
)

EVALUATION_REGRESSIONS_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_evaluation_regressions_total",
    "Total regression-threshold failures detected during a run comparison, by category.",
    ["category"],
)


def observe_evaluation_run_terminal(*, outcome: str) -> None:
    """The single call site every EvaluationRun terminal-transition
    recorder must go through (``evaluations/services.py::finalize_evaluation_run``
    and ``cancel_evaluation_run``)."""
    outcome_label = outcome if outcome in _EVALUATION_RUN_OUTCOMES else "failed"
    EVALUATION_RUNS_TOTAL.labels(outcome=outcome_label).inc()


def observe_evaluation_case_terminal(*, outcome: str, duration_seconds: float | None) -> None:
    """The single call site every EvaluationResult terminal-transition
    recorder must go through (``evaluations/services.py::execute_evaluation_case``)."""
    outcome_label = outcome if outcome in _EVALUATION_CASE_OUTCOMES else "execution_failed"
    EVALUATION_CASES_TOTAL.labels(outcome=outcome_label).inc()
    if duration_seconds is not None:
        EVALUATION_CASE_DURATION_SECONDS.labels(outcome=outcome_label).observe(duration_seconds)


def observe_evaluation_regression(*, category: str) -> None:
    category_label = category if category in _EVALUATION_REGRESSION_CATEGORIES else "pass_rate"
    EVALUATION_REGRESSIONS_TOTAL.labels(category=category_label).inc()


# ---------------------------------------------------------------------------
# Durable delivery / webhook reliability (Phase 11 Block 4)
#
# Every metric here represents an authoritative, already-committed
# ``notifications.models.Delivery``/``DeliveryAttempt`` state transition —
# never a Celery task execution and never a broker publish, which are
# disposable transport, not ownership (see ``notifications/services.py``'s
# own module docstring). ``channel`` (``notification``/``webhook``, 2 values,
# ``DeliveryChannel``-owned) is the only per-delivery label most of these
# carry; nothing here is ever labeled by a delivery/attempt/workspace/
# endpoint/event id, a URL, a hostname, an IP, or raw exception/response
# text (section 5 of the Block 4 brief — a hard gate, no exceptions).
# ---------------------------------------------------------------------------

_DELIVERY_CHANNELS = frozenset({"notification", "webhook", "channel_response"})


def _delivery_channel_label(channel: str) -> str:
    return channel if channel in _DELIVERY_CHANNELS else "notification"


# --- Creation -------------------------------------------------------------

DELIVERIES_CREATED_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_deliveries_created_total",
    "Total Delivery rows successfully committed, by channel.",
    ["channel"],
)


def observe_delivery_created(*, channel: str) -> None:
    """The single call site for a newly-committed ``Delivery`` row
    (``notifications/services.py``'s ``create_delivery``, scheduled via
    ``transaction.on_commit`` so a rolled-back creation is never counted —
    section 6). A reused logical delivery (``notification.send`` replay
    finding an existing ``NotificationDelivery``, a webhook redrive) never
    calls ``create_delivery`` at all, so this never double-counts those
    cases by construction — see ``observe_delivery_redrive`` below."""
    DELIVERIES_CREATED_TOTAL.labels(channel=_delivery_channel_label(channel)).inc()


# --- Attempts ---------------------------------------------------------------

#: Incremented once per genuine claim/reclaim ownership acquisition — the
#: exact moment a real ``DeliveryAttempt`` row is created (section 7). A
#: redelivered/duplicate Celery message that finds nothing claimable never
#: reaches this call site at all.
DELIVERY_ATTEMPTS_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_delivery_attempts_total",
    "Total DeliveryAttempt rows that actually obtained ownership, by channel.",
    ["channel"],
)

#: ``outcome`` (4 values, bounded): ``succeeded`` / ``retryable_failure`` /
#: ``terminal_failure`` (both from ``complete_delivery_failure``, split by
#: whether the delivery could still retry) / ``abandoned`` (an expired
#: claim's orphaned in-flight attempt, observed by the reclaim path — see
#: ``observe_delivery_claim_recovery``). Seconds-scale buckets (section 8,
#: 55): this measures the external attempt itself — DNS/connection/response
#: handling for webhooks, the provider call for notifications — never
#: PENDING wait, retry backoff, or approval wait.
DELIVERY_ATTEMPT_DURATION_SECONDS = Histogram(
    f"{METRIC_NAMESPACE}_delivery_attempt_duration_seconds",
    "DeliveryAttempt execution duration in seconds, by channel and outcome.",
    ["channel", "outcome"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)

_DELIVERY_ATTEMPT_OUTCOMES = frozenset(
    {"succeeded", "retryable_failure", "terminal_failure", "abandoned"}
)

#: Bounded, server-owned failure taxonomy (section 9, 24) — never a raw
#: ``safe_error_code`` string (that set is broader — includes per-business
#: ``IntegrationError`` codes and per-HTTP-status ``webhook_http_4xx``-style
#: codes — see ``_delivery_error_category`` below, which maps *into* this
#: fixed set). Only incremented for a failed attempt (``retryable_failure``/
#: ``terminal_failure``/``abandoned``) — never for ``succeeded``.
DELIVERY_ATTEMPT_FAILURES_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_delivery_attempt_failures_total",
    "Total failed DeliveryAttempt outcomes, by channel and safe error category.",
    ["channel", "error_category"],
)

_DELIVERY_ERROR_CATEGORIES = frozenset(
    {
        "timeout",
        "rate_limit",
        "connection",
        "dns",
        "tls",
        "blocked_destination",
        "remote_4xx",
        "remote_5xx",
        "auth",
        "configuration",
        "invalid_request",
        "redirect",
        "internal",
        "other",
    }
)

#: Maps a delivery-domain ``safe_error_code`` (``notifications.errors``,
#: ``webhooks.errors``/``classification.classify_http_status``,
#: ``integrations.errors.IntegrationError.code`` — every code
#: ``complete_delivery_failure`` ever receives) to the fixed category set
#: above. Deliberately a lookup table, not string-prefix heuristics on
#: caller-supplied text (section 9): every key is a real, stable code this
#: codebase itself defines — an unrecognized code (a future error type this
#: table has not been updated for) safely collapses to ``"other"``, never a
#: new label value.
_ERROR_CODE_TO_CATEGORY: dict[str, str] = {
    # webhooks.errors
    "webhook_invalid_url": "configuration",
    "webhook_destination_blocked": "blocked_destination",
    "webhook_dns_resolution_failed": "dns",
    "webhook_endpoint_disabled": "configuration",
    "webhook_signing_not_configured": "configuration",
    "webhook_redirect_rejected": "redirect",
    "webhook_timeout": "timeout",
    "webhook_connection_failed": "connection",
    "webhook_tls_error": "tls",
    "webhook_invalid_event_type": "configuration",
    "webhook_unexpected_transport_error": "internal",
    "webhook_delivery_unexpected_error": "internal",
    "webhook_delivery_missing": "internal",
    "webhook_not_found": "internal",
    # notifications
    "notification_delivery_unexpected_error": "internal",
    "notification_delivery_missing": "internal",
    # integrations.errors.IntegrationError (Phase 7 taxonomy, reused as-is —
    # section 28 forbids inventing a second classifier for these).
    "integration_not_configured": "configuration",
    "integration_disabled": "configuration",
    "integration_authentication_failed": "auth",
    "integration_permission_denied": "auth",
    "integration_rate_limited": "rate_limit",
    "integration_timeout": "timeout",
    "integration_temporarily_unavailable": "other",
    "integration_invalid_request": "invalid_request",
    "integration_not_found": "invalid_request",
    "integration_conflict": "invalid_request",
    "integration_malformed_response": "internal",
    "integration_configuration_error": "configuration",
    "integration_provider_not_supported": "configuration",
    "customer_not_found": "invalid_request",
    "order_not_found": "invalid_request",
    "shipment_not_found": "invalid_request",
    "ticket_not_found": "invalid_request",
    "payment_not_found": "invalid_request",
    "refund_not_allowed_by_provider": "invalid_request",
    "refund_already_exists": "invalid_request",
    "calendar_slot_unavailable": "invalid_request",
    "booking_already_exists": "invalid_request",
    "integration_unknown_error": "other",
}


def _delivery_error_category(safe_error_code: str) -> str:
    if safe_error_code.startswith("webhook_http_"):
        # ``classify_http_status`` mints one code per status code
        # (``webhook_http_404``, ``webhook_http_500``, ...) — deliberately
        # never used as a label value directly (unbounded-in-principle);
        # collapsed to the 4xx/5xx status class instead (section 9, 22-23).
        digits = safe_error_code.removeprefix("webhook_http_")
        if digits[:1] == "4":
            return "remote_4xx"
        if digits[:1] == "5":
            return "remote_5xx"
        return "other"
    return _ERROR_CODE_TO_CATEGORY.get(safe_error_code, "other")


def observe_delivery_attempt_claimed(*, channel: str) -> None:
    """The single call site for genuine claim/reclaim ownership acquisition
    (``notifications/services.py``'s ``_claim_row``, on commit — section 7).
    Called for *both* a plain due claim and an expired-claim reclaim; the
    reclaim path additionally calls ``observe_delivery_claim_recovery``."""
    DELIVERY_ATTEMPTS_TOTAL.labels(channel=_delivery_channel_label(channel)).inc()


def observe_delivery_attempt_outcome(
    *, channel: str, outcome: str, duration_seconds: float | None, safe_error_code: str = ""
) -> None:
    """The single call site every completed ``DeliveryAttempt`` outcome
    goes through (``complete_delivery_success``/``complete_delivery_failure``
    on commit, and the reclaim path's own ``abandoned`` observation).
    ``safe_error_code`` is only consulted for a failed outcome, and only
    ever to look up a bounded category — never stored or labeled itself."""
    channel_label = _delivery_channel_label(channel)
    outcome_label = outcome if outcome in _DELIVERY_ATTEMPT_OUTCOMES else "terminal_failure"
    if duration_seconds is not None:
        DELIVERY_ATTEMPT_DURATION_SECONDS.labels(
            channel=channel_label, outcome=outcome_label
        ).observe(duration_seconds)
    if outcome_label != "succeeded":
        category = _delivery_error_category(safe_error_code)
        category_label = category if category in _DELIVERY_ERROR_CATEGORIES else "other"
        DELIVERY_ATTEMPT_FAILURES_TOTAL.labels(
            channel=channel_label, error_category=category_label
        ).inc()


# --- Retries / terminal transitions -----------------------------------------

DELIVERY_RETRIES_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_delivery_retries_total",
    "Total committed Delivery transitions to RETRY_SCHEDULED, by channel.",
    ["channel"],
)


def observe_delivery_retry_scheduled(*, channel: str) -> None:
    """The single call site for a committed DB transition to
    ``DeliveryStatus.RETRY_SCHEDULED`` (``complete_delivery_failure``, on
    commit — section 10). Deliberately distinct from
    ``observability.metrics.observe_celery_task``'s own ``outcome="retry"``
    label: Phase 10 retry authority is PostgreSQL, never Celery — the two
    counters measure different layers and must never be conflated."""
    DELIVERY_RETRIES_TOTAL.labels(channel=_delivery_channel_label(channel)).inc()


#: ``outcome`` (3 values): ``delivered`` / ``failed`` (retryable failure,
#: attempt budget exhausted) / ``dead`` (explicit non-retryable terminal
#: failure) — the actual ``DeliveryStatus`` terminal split (section 11),
#: kept distinguishable rather than merged.
DELIVERY_TERMINAL_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_delivery_terminal_total",
    "Total committed Delivery terminal transitions, by channel and outcome.",
    ["channel", "outcome"],
)

_DELIVERY_TERMINAL_OUTCOMES = frozenset({"delivered", "failed", "dead"})

#: end-to-end (creation -> DELIVERED, including any retries/backoff) —
#: minutes-scale buckets (section 12, 55), deliberately not the same bucket
#: set as attempt duration: this can legitimately span a full retry
#: schedule, not just one external call.
DELIVERY_END_TO_END_DURATION_SECONDS = Histogram(
    f"{METRIC_NAMESPACE}_delivery_end_to_end_duration_seconds",
    "Delivery end-to-end duration in seconds (created_at to DELIVERED), by channel.",
    ["channel"],
    buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, 300, 900, 3600),
)


def observe_delivery_terminal(
    *, channel: str, outcome: str, end_to_end_duration_seconds: float | None = None
) -> None:
    """The single call site for a committed ``Delivery`` terminal
    transition (``complete_delivery_success``'s ``delivered`` outcome,
    ``complete_delivery_failure``'s ``failed``/``dead`` outcomes — both on
    commit, and both already guarding their own single-fire DB transition
    with ``select_for_update`` + an active-claim check, section 15 of the
    Block 3 remediation's same guarantee applied here). Only ``delivered``
    ever passes a duration (section 12) — FAILED/DEAD deliveries never
    fabricate one."""
    channel_label = _delivery_channel_label(channel)
    outcome_label = outcome if outcome in _DELIVERY_TERMINAL_OUTCOMES else "failed"
    DELIVERY_TERMINAL_TOTAL.labels(channel=channel_label, outcome=outcome_label).inc()
    if outcome_label == "delivered" and end_to_end_duration_seconds is not None:
        DELIVERY_END_TO_END_DURATION_SECONDS.labels(channel=channel_label).observe(
            end_to_end_duration_seconds
        )


# --- Claim recovery / broker publication / redrive --------------------------

DELIVERY_CLAIM_RECOVERIES_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_delivery_claim_recoveries_total",
    "Total expired CLAIMED deliveries successfully reclaimed, by channel.",
    ["channel"],
)


def observe_delivery_claim_recovery(*, channel: str) -> None:
    """The single call site for a successful expired-claim reclaim
    (``notifications/services.py``'s ``_claim_row``, the
    ``reclaim_expired_delivery`` branch only — section 13). One observation
    per reclaimed delivery, regardless of how many sweeps republished its
    id (``notifications/recovery.py`` never calls this itself — only the
    claim primitive that actually changed ownership does, section 15)."""
    DELIVERY_CLAIM_RECOVERIES_TOTAL.labels(channel=_delivery_channel_label(channel)).inc()


#: ``source`` (2 values): ``initial`` (``create_delivery``'s own
#: post-commit dispatch, or a manual redrive's) / ``sweeper`` (the Block 4
#: recovery sweepers republishing a due/expired-claim delivery id).
DELIVERY_BROKER_PUBLICATION_FAILURES_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_delivery_broker_publication_failures_total",
    "Total best-effort Celery publication failures, by channel and source.",
    ["channel", "source"],
)

#: Phase 16 Checkpoint 3 (Part E): ``agents.recovery.recover_stuck_agent_runs``
#: and ``evaluations.recovery.recover_stuck_evaluation_runs`` previously only
#: emitted a structured log line — invisible to any dashboard/alert built on
#: metrics. ``domain`` (2 values: ``agent`` / ``evaluation``) is the only
#: label — never a run id (would be unbounded cardinality) or a workspace/
#: customer id (forbidden by this project's metric-labeling rules).
STUCK_RUN_RECOVERIES_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_stuck_run_recoveries_total",
    "Total AgentRun/EvaluationRun rows recovered (failed) by the stuck-worker sweeper, by domain.",
    ["domain"],
)


def observe_stuck_run_recovery(*, domain: str, count: int = 1) -> None:
    """Called once per sweep by ``agents.recovery``/``evaluations.recovery``
    with the number of rows actually recovered in that sweep (0 is a valid,
    intentionally-skipped call — see each call site)."""
    if count <= 0:
        return
    STUCK_RUN_RECOVERIES_TOTAL.labels(domain=domain).inc(count)


_DELIVERY_PUBLICATION_SOURCES = frozenset({"initial", "sweeper"})


def observe_delivery_broker_publication_failure(*, channel: str, source: str) -> None:
    """The single call site for a failed best-effort Celery publish
    (``notifications/services.py``'s ``dispatch_delivery_for_processing``,
    on the caught broker/transport exception — section 14). Never implies
    an external attempt occurred and never consumes attempt budget — the
    delivery stays exactly as durably persisted, recoverable by the next
    sweep."""
    source_label = source if source in _DELIVERY_PUBLICATION_SOURCES else "initial"
    DELIVERY_BROKER_PUBLICATION_FAILURES_TOTAL.labels(
        channel=_delivery_channel_label(channel), source=source_label
    ).inc()


DELIVERY_REDRIVES_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_delivery_redrives_total",
    "Total accepted manual Delivery redrives, by channel.",
    ["channel"],
)


def observe_delivery_redrive(*, channel: str) -> None:
    """The single call site for an *accepted* manual redrive
    (``webhooks/services.py``'s ``redrive_webhook_delivery``, on commit —
    section 27, 29). A rejected redrive request (wrong status, disabled
    endpoint) never reaches this — no exception path calls it. Never
    implies a new logical ``Delivery`` was created (see
    ``observe_delivery_created``'s own docstring) — the same row, same
    attempt history, continues."""
    DELIVERY_REDRIVES_TOTAL.labels(channel=_delivery_channel_label(channel)).inc()


# --- Webhook-specific: receiver response class / destination rejection -----

#: ``status_class`` (``2xx``/``3xx``/``4xx``/``5xx`` — never a raw status
#: code, section 22-23). 3xx is recorded defensively even though Phase 10
#: never persists it as a delivery outcome (a redirect response is rejected
#: before classification, section 23 — see ``webhooks/transport.py``); kept
#: here only so a future transport change can never silently create an
#: unbounded label rather than being caught by this fixed set.
WEBHOOK_RESPONSES_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_webhook_responses_total",
    "Total webhook receiver HTTP responses observed, by status class.",
    ["status_class"],
)

_WEBHOOK_STATUS_CLASSES = frozenset({"2xx", "3xx", "4xx", "5xx"})


def observe_webhook_response(*, status_code: int) -> None:
    """The single call site for an actually-received webhook receiver
    response (``notifications/services.py``'s completion functions, only
    when ``response_status_code`` is present — i.e. only ever for the
    webhook channel, section 22). A transport failure that never received a
    response (timeout/connection/DNS/TLS) never calls this — see
    ``DELIVERY_ATTEMPT_FAILURES_TOTAL`` for those."""
    status_class = f"{status_code // 100}xx"
    label = status_class if status_class in _WEBHOOK_STATUS_CLASSES else "other"
    if label == "other":
        return
    WEBHOOK_RESPONSES_TOTAL.labels(status_class=label).inc()


#: Fixed, server-owned SSRF/destination-validation rejection taxonomy
#: (section 25), drawn directly from ``webhooks.security``'s actual
#: exception classes — never hostname/IP/URL.
_WEBHOOK_DESTINATION_REJECTION_REASONS = frozenset(
    {"invalid_url", "destination_blocked", "dns_error"}
)

WEBHOOK_DESTINATION_REJECTIONS_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_webhook_destination_rejections_total",
    "Total webhook destinations rejected at send-time validation, by reason.",
    ["reason"],
)


def observe_webhook_destination_rejection(*, reason: str) -> None:
    """The single call site for a send-time destination-validation
    rejection (``webhooks/services.py``'s ``handle_webhook_delivery_attempt``,
    at the point ``parse_webhook_url``/``resolve_and_validate`` raise —
    section 25). Deliberately observed at the *actual attempted send*, not
    endpoint-creation time (``_best_effort_ssrf_check`` never calls this) —
    DNS can legitimately change between creation and send."""
    reason_label = (
        reason if reason in _WEBHOOK_DESTINATION_REJECTION_REASONS else "destination_blocked"
    )
    WEBHOOK_DESTINATION_REJECTIONS_TOTAL.labels(reason=reason_label).inc()


# --- Backlog / recovery-lag gauges (DB-derived — section 16-21) -------------
#
# ``multiprocess_mode="mostrecent"`` (not the ``Gauge`` default of summing
# every process's last-written value): these gauges represent one current
# global count, not a per-process contribution to a total, so summing across
# however many Gunicorn workers have ever handled a ``/metrics/`` scrape
# would silently multiply the real value. "Most recently written, across
# whichever process wrote last" is the correct aggregation for a value that
# is recomputed fresh, from the same source of truth, by whichever process
# happens to serve a given scrape (see ``refresh_delivery_backlog_gauges``
# below and its one call site, ``observability/views.py::metrics_view`` —
# never a Celery worker's own metrics listener, section 20).

DELIVERY_DUE_COUNT = Gauge(
    f"{METRIC_NAMESPACE}_delivery_due_count",
    "Current count of Deliveries eligible to be claimed now, by channel.",
    ["channel"],
    multiprocess_mode="mostrecent",
)

DELIVERY_EXPIRED_CLAIM_COUNT = Gauge(
    f"{METRIC_NAMESPACE}_delivery_expired_claim_count",
    "Current count of CLAIMED Deliveries whose lease has expired, by channel.",
    ["channel"],
    multiprocess_mode="mostrecent",
)

#: Seconds a delivery has been overdue: ``now - next_attempt_at`` for the
#: oldest currently-eligible row (section 18 — never ``created_at``, which
#: would misrepresent a delivery legitimately scheduled into the future by
#: retry backoff). ``0`` when there is no due backlog at all (documented
#: choice, section 18) rather than omitting the sample — an absent time
#: series and a healthy "0 lag" series are easy to conflate in a dashboard/
#: alert expression, so this always reports a value once any delivery of
#: that channel has ever existed... in practice: once this gauge has ever
#: been refreshed for that channel (see ``refresh_delivery_backlog_gauges``).
DELIVERY_OLDEST_DUE_AGE_SECONDS = Gauge(
    f"{METRIC_NAMESPACE}_delivery_oldest_due_age_seconds",
    "Age in seconds of the oldest currently-due Delivery, by channel (0 if none).",
    ["channel"],
    multiprocess_mode="mostrecent",
)


def refresh_delivery_backlog_gauges(*, now=None) -> None:
    """Recompute the three DB-derived backlog gauges above from PostgreSQL
    and set them (section 16-19).

    Deliberately **not** called from :func:`render_metrics` (which the
    Celery worker's own metrics listener also calls, ``config/celery_metrics.py``
    — section 20): every Celery child would otherwise issue these queries on
    every scrape. This function has exactly one call site,
    ``observability/views.py::metrics_view`` (the Django/Gunicorn scrape
    path), so the query cost is bounded by however often *that* endpoint is
    scraped, never multiplied by worker-process count.

    Two bounded aggregate queries total (section 19) — one grouped
    ``COUNT``/``MIN`` over the due-claimable selector, one grouped ``COUNT``
    over the expired-claim selector — never one query per delivery, never a
    full row fetch. Every known channel is always set explicitly (including
    to 0), even when a channel currently has no matching rows: leaving a
    channel unset here would let a stale prior value linger under
    ``mostrecent`` aggregation forever once that channel's backlog clears.

    Fails open (section 21, 41): a DB error here is logged and swallowed —
    it never prevents the rest of a metrics scrape from rendering, and it
    never touches business/delivery state (this function only reads).
    """
    from django.db.models import Count, Min
    from django.utils import timezone as _timezone

    from notifications.selectors import due_claimable_deliveries, expired_claimed_deliveries

    now = now or _timezone.now()
    try:
        due_by_channel = {
            row["channel"]: row
            for row in due_claimable_deliveries(now=now)
            .values("channel")
            .annotate(count=Count("id"), oldest=Min("next_attempt_at"))
        }
        expired_by_channel = {
            row["channel"]: row["count"]
            for row in expired_claimed_deliveries(now=now)
            .values("channel")
            .annotate(count=Count("id"))
        }
        for channel in _DELIVERY_CHANNELS:
            due_row = due_by_channel.get(channel)
            due_count = due_row["count"] if due_row else 0
            DELIVERY_DUE_COUNT.labels(channel=channel).set(due_count)
            if due_row and due_row["oldest"] is not None:
                oldest_age = max((now - due_row["oldest"]).total_seconds(), 0.0)
            else:
                oldest_age = 0.0
            DELIVERY_OLDEST_DUE_AGE_SECONDS.labels(channel=channel).set(oldest_age)
            DELIVERY_EXPIRED_CLAIM_COUNT.labels(channel=channel).set(
                expired_by_channel.get(channel, 0)
            )
    except Exception:  # noqa: BLE001 - telemetry must fail open
        logger.warning("delivery_backlog_gauge_refresh_failed", extra={"event": "metrics_error"})


# ---------------------------------------------------------------------------
# Multi-channel ingress (Phase 13) — every label is a small, bounded,
# code-owned enum value (``ChannelType``/a fixed outcome/failure-taxonomy
# set); never a workspace/customer/conversation/message/provider-event id,
# email address, phone number, session token, or raw provider name (section
# 47).
# ---------------------------------------------------------------------------

_CHANNEL_TYPES = frozenset({"web_chat", "email", "generic_webhook"})


def _channel_label(channel: str) -> str:
    return channel if channel in _CHANNEL_TYPES else "generic_webhook"


CHANNEL_INGRESS_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_channel_ingress_total",
    "Total inbound channel events received, by channel.",
    ["channel"],
)


def observe_channel_ingress_received(*, channel: str) -> None:
    """The single call site for a newly-committed ``InboundChannelEvent``
    row (``channel_ingress/services.py``'s ``ingest_channel_event``,
    scheduled via ``transaction.on_commit`` so a rolled-back creation is
    never counted — a duplicate delivery that resolves to the existing row
    never calls this a second time, by construction)."""
    CHANNEL_INGRESS_TOTAL.labels(channel=_channel_label(channel)).inc()


_CHANNEL_INGRESS_OUTCOMES = frozenset({"processed", "failed"})

CHANNEL_INGRESS_PROCESSING_SECONDS = Histogram(
    f"{METRIC_NAMESPACE}_channel_ingress_processing_seconds",
    "Inbound channel event processing duration in seconds, by channel and outcome.",
    ["channel", "outcome"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)


def observe_channel_ingress_terminal(
    *, channel: str, outcome: str, duration_seconds: float | None
) -> None:
    """The single call site for a terminal (``processed``/``failed``)
    inbound channel event, observed from
    ``channel_ingress.services.process_inbound_channel_event``."""
    if duration_seconds is None:
        return
    outcome_label = outcome if outcome in _CHANNEL_INGRESS_OUTCOMES else "failed"
    CHANNEL_INGRESS_PROCESSING_SECONDS.labels(
        channel=_channel_label(channel), outcome=outcome_label
    ).observe(duration_seconds)


CHANNEL_INGRESS_DUPLICATES_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_channel_ingress_duplicates_total",
    "Total inbound channel events recognized as a duplicate of an existing event, by channel.",
    ["channel"],
)


def observe_channel_ingress_duplicate(*, channel: str) -> None:
    """The single call site for a request that resolved to an *existing*
    ``InboundChannelEvent`` row rather than creating a new one (section 11)."""
    CHANNEL_INGRESS_DUPLICATES_TOTAL.labels(channel=_channel_label(channel)).inc()


CHANNEL_SIGNATURE_FAILURES_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_channel_signature_failures_total",
    "Total inbound webhook signature verification failures, by channel.",
    ["channel"],
)


def observe_channel_signature_failure(*, channel: str) -> None:
    """The single call site for a rejected inbound signature (section 21) —
    never distinguishes *why* it failed in the metric itself (that
    distinction belongs to the safe failure-code taxonomy, not a
    Prometheus label — section 47's bounded-cardinality rule)."""
    CHANNEL_SIGNATURE_FAILURES_TOTAL.labels(channel=_channel_label(channel)).inc()


# ---------------------------------------------------------------------------
# Rendering (multiprocess-aware — section 29)
# ---------------------------------------------------------------------------


def render_metrics() -> bytes:
    """Render the current Prometheus exposition payload.

    Branches on ``PROMETHEUS_MULTIPROC_DIR`` at *render* time so a scrape
    always aggregates whatever is currently on disk. This does not change
    which value class an already-constructed metric object uses (that was
    fixed at import time, per the module docstring) — it only decides how
    this function collects the numbers for the response."""
    multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if multiproc_dir:
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry, path=multiproc_dir)
        return generate_latest(registry)
    return generate_latest()
