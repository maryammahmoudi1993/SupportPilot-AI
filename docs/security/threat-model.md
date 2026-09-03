# Backend Threat Model

This document is a concise, implementation-grounded threat model for the
SupportPilot AI backend, written as part of Phase 15 (Backend Security &
Authorization Hardening). It describes real assets, actors, and trust
boundaries as they exist in this codebase today — not aspirational or
compliance-oriented claims. Where a boundary depends on deployment choices
outside this repository, that is called out explicitly rather than assumed
away.

## Assets

- **Customer and business data**: customer records, conversations, tickets,
  orders/payments looked up through integrations, knowledge documents.
- **Workspace configuration**: agent definitions/versions (including system
  prompts), tool bindings, policy rules, integration connections.
- **Secrets**: Django `SECRET_KEY`/JWT signing material, integration
  credentials (Stripe, Google, SMTP, etc.), webhook and channel signing
  secrets, refresh tokens, CSRF tokens.
- **Execution integrity**: the invariant that a tool only ever runs when a
  registered binding, validated input, and a deterministic policy/approval
  decision all agree — never because an LLM said so.
- **Audit history**: an accurate, append-only record of security-sensitive
  actions.

## Actors

- **Authenticated workspace member** (owner/admin/support_manager/
  support_agent/viewer) — the primary trusted-but-bounded actor; RBAC
  narrows what each role can mutate, but any active member can read most
  workspace configuration (`docs/security/authentication-tenancy-rbac.md`).
- **Unauthenticated public visitor** — reaches only the narrow public
  ingress surface (webchat session/message endpoints, signed inbound
  webhooks) and the login/auth endpoints.
- **The LLM provider** (real, or a customer-configured integration) —
  treated as an *untrusted proposer*: it can suggest a tool call or a reply,
  but never itself authorizes anything (see "LLM / untrusted data" below).
- **A malicious or compromised external service** on the other end of an
  outbound integration (SMTP host, webhook URL, Stripe/Google Calendar
  endpoints) — relevant to the SSRF/outbound-networking boundary.
- **An operator/infra actor** (reverse proxy, Celery worker, database) —
  assumed to run the code as shipped; this model does not cover compromise
  of the underlying infrastructure itself.

## Trust boundaries

### Tenant isolation

Every workspace-scoped view resolves `self.workspace`/`self.membership`
inside `WorkspaceScopedMixin.check_permissions()` before any view logic
runs (`workspaces/views.py`), and returns 404 — never 403 — for
cross-tenant access, to avoid an existence oracle. Models without their own
`workspace` foreign key (`AgentVersion`, `PolicyVersion`, `PolicyRule`,
evaluation snapshots/results, `ApprovalDecision`) are only reachable
through a parent chain that is itself workspace-scoped; this nested-IDOR
class was exercised directly by a 71-test cross-tenant matrix across
agents, integrations, policies, knowledge, evaluations, and channel_ingress
(Phase 15 checkpoint 3) with zero findings.

### Auth / RBAC

JWT access tokens (short-lived, JSON body) and refresh tokens (`HttpOnly`
cookie, rotated and blacklisted on use) are described in
`docs/security/authentication-tenancy-rbac.md`. Server-side RBAC
(`Can*` permission classes) is authoritative; the pattern used throughout
the codebase is "any active workspace member can read configuration,
mutation requires an elevated role" — applied consistently across agents,
tools, and policies (`agents/views.py`, `tools/views.py`,
`policies/views.py`).

### Public ingress

The only unauthenticated write surfaces are the webchat session/message
endpoints and signed channel-ingress webhooks
(`channel_ingress/security.py`) — both rate-limited by an identity that is
never a caller-supplied header (`DRF_NUM_PROXIES`-gated; `X-Forwarded-For`
is trusted only up to the configured, explicit proxy count, and
`X-Real-IP`/`Forwarded` are never consulted anywhere in this codebase).
Signed ingress payloads are verified for signature, replay window, and
idempotent redelivery before any domain logic runs.

### LLM / untrusted data

The agent runtime (`agents/orchestration.py`, `agents/llm_context.py`)
assembles the model context from a trusted system prompt plus two
explicitly *untrusted* envelopes: retrieved knowledge (`REFERENCE
MATERIAL`/`END REFERENCE MATERIAL`) and tool results (`TOOL RESULT —
UNTRUSTED EXTERNAL DATA`/`END TOOL RESULT`, redacted before inclusion).
Neither envelope, nor the raw customer message, is ever parsed for
commands, tool names, workspace IDs, or approval state — those are always
server-derived from `AgentRun`/`ToolBinding`/`PolicyVersion` database rows.
A proposed tool call is validated against the typed registry and the
`AgentVersion`'s bindings (exact-match only — no fuzzy/case-insensitive
resolution), then against a Pydantic input schema (`extra="forbid"`), then
against a deterministic policy engine that decides `ALLOW`/`DENY`/
`REQUIRE_APPROVAL` — the model's own output is never sufficient to execute
a side effect. Evaluation runs reuse this exact same execution boundary
with only the LLM provider substituted for a deterministic fake, so an
adversarial prompt embedded in an `EvaluationCase` is subject to the same
gates as a live customer message.

### Tool / policy / approval boundary

`tools/execution.py::execute_tool` is the single, documented entry point
from a normalized tool request to a handler invocation; no other module
invokes a tool handler directly, and there is deliberately no direct
"execute this tool" API endpoint. Every reachable path — the agent graph,
Celery task redelivery, approval resume, evaluation execution, and
channel-triggered orchestration — converges on it. A strict, atomic
conditional `UPDATE` reserves the concurrent tool-call budget immediately
before a handler runs (never at proposal or approval-pending time), and
approval decisions are idempotent (a repeated identical decision is a
no-op; a conflicting one is rejected).

### SSRF / outbound networking

The two workspace-controlled outbound destinations (webhook delivery,
SMTP) both validate the resolved destination address against a fail-closed
allowlist (rejecting private/loopback/link-local/multicast/metadata
ranges, alternate IP notations, and mixed-DNS answers) and pin the
connection to the resolved IP for the life of the connection while
preserving the original hostname for TLS SNI/certificate verification —
closing the DNS-rebinding TOCTOU window between validation and connection.
Redirects are rejected outright rather than revalidated. Other outbound
integrations (Stripe, Google Calendar) target a fixed vendor host, not a
workspace-supplied one, so this class of risk does not apply to them.

### Async task trust boundaries

Every security-relevant Celery task accepts a single opaque entity ID and
re-derives workspace, ownership, and relationship state from the database
inside the service layer it calls — no task trusts a caller-supplied
pairing of two related IDs. Redelivery/duplicate/stale invocation is made
safe by claim-token and conditional-`UPDATE` patterns already present
across agent-run claiming, tool-execution idempotency, tool-budget
reservation, and delivery claiming (webhooks and notifications) — a stale
or redelivered task cannot regress completed state or double-fire an
external side effect.

### Secrets

Integration credentials, webhook signing secrets, and channel signing
secrets are stored only as ciphertext (Fernet, with rotation support);
serializers exclude them from every read path, exposing only booleans
(`credentials_configured`) and version numbers. A newly created or rotated
secret is returned in plaintext exactly once, via a dedicated one-shot
response shape, never re-derivable from a subsequent read. A shared,
deliberately over-inclusive redaction utility
(`common/redaction.py:redact`) strips any dict value whose key looks
secret-shaped before it reaches structured logs, tool-result messages, or
persisted tool-argument records.

### Rate limits

Unauthenticated throttle identity is `REMOTE_ADDR` unless an explicit,
deployment-configured `DRF_NUM_PROXIES` says otherwise (default `0`); no
caller-supplied header can rotate a throttle bucket under the default
configuration. Authenticated throttling keys on `request.user.pk`. A cache
outage fails closed to a `503`, never to unlimited execution.

### Uploads

Filenames are validated against path-traversal (parent-directory
segments, absolute paths, drive letters, UNC paths, null bytes) before any
filesystem interaction; MIME type, page count, and total size are all
bounded before parsing untrusted document content.

### Audit integrity

`audit.services.record_event()` is the only supported way to create an
`AuditEvent`; there is no public write or read API for it at all (no
`audit/urls.py`), so actor/workspace/action/target are always Python-level
arguments a trusted service function supplies from authenticated/server
context — never client JSON. Audit metadata payloads observed across
credential rotation, webhook/channel secret rotation, and approval
decisions contain only IDs, provider names, booleans, and enum values —
never a password, Authorization header, signature, or refresh token.

## Residual deployment risks

These are real, but they are deployment decisions outside this
repository's scope, not defects in the current implementation:

- **Reverse-proxy header hygiene**: `DRF_NUM_PROXIES` trusting N hops of
  `X-Forwarded-For` is only as safe as the actual reverse proxy in front of
  the application stripping/overwriting that header before it reaches
  Django. This codebase does not and cannot verify that a specific
  deployment's proxy does so.
- **HSTS/preload**: `SECURE_HSTS_SECONDS`/`INCLUDE_SUBDOMAINS`/`PRELOAD`
  are enabled automatically whenever `DEBUG=False`, which is correct only
  once a production domain is genuinely served over TLS everywhere,
  including all subdomains. Submitting the domain to browser preload lists
  is an irreversible-in-practice decision that belongs to whoever owns
  that domain at deployment time, not to this codebase.
- **SMTP implicit-TLS (`SMTPS`) mode**: the current SMTP provider adapter
  pins the connection (DNS-rebinding-safe) for STARTTLS mode; an
  implicit-TLS mode is not currently exposed through the credentials
  schema, so it has not been built or exercised. Adding it would need the
  same pinning treatment before being enabled.
- **Celery Beat/periodic task packaging**: sweep/recovery tasks
  (approval expiry, delivery redrive, stuck-inbound-event recovery) assume
  a correctly configured Celery Beat schedule in the deployment; packaging
  and scheduling that reliably is an operations concern documented in
  `docs/operations/deployment.md`, not an application-layer control.
- **Content-Security-Policy**: no CSP is configured. This backend is a
  JSON API consumed by a separate SPA frontend, not a server-rendered HTML
  surface, so CSP's usual XSS-mitigation role belongs to the frontend's own
  deployment; revisit if this backend ever serves rendered HTML directly.

No compliance claims (SOC 2, PCI, HIPAA, or similar) are made or implied
by this document.
