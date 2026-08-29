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

import os

from prometheus_client import CONTENT_TYPE_LATEST as METRICS_CONTENT_TYPE
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    multiprocess,
)

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

#: Labels: ``trigger`` (``AgentRunTrigger`` — manual/conversation/ticket/api,
#: 4 values, code-owned), ``outcome`` (one of ``AGENT_RUN_TERMINAL_STATUSES``
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

_AGENT_RUN_TRIGGERS = frozenset({"manual", "conversation", "ticket", "api"})
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
