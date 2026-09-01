# Multi-Channel Ingress

Phase 13 adds channel transport adapters — web chat, a signed generic
webhook, and a signed email-style webhook — that all funnel into the *same*
production customer-message orchestration Phase 9 built. There is one agent
system; channels are transport adapters onto its existing boundary, never a
second runtime.

## Canonical inbound architecture

```
Provider / Web Chat
        |
channel authentication (HMAC signature | session capability)
        |
channel adapter parse + normalize
        |
CanonicalInboundMessage
        |
InboundChannelEvent (durable, deduped)
        |
identity resolution -> Customer
        |
conversation resolution -> Conversation
        |
conversations.services.create_inbound_message -> Message
        |
agents.orchestration.start_support_agent_run  (existing Phase 9 seam)
        |
existing tools / policy / approvals / handoff / response
        |
channel response routing (Phase 10 Delivery engine, email only)
```

Every step above lives in `channel_ingress/`; nothing downstream of
`CanonicalInboundMessage` ever sees a raw provider payload again.

## Supported channels (this phase)

| Channel | Auth model | Adapter |
|---|---|---|
| `web_chat` | opaque session capability (section 17) | `channel_ingress.webchat` — no `ChannelAdapter`, a distinct security model |
| `email` | HMAC-SHA256 signed JSON envelope | `channel_ingress.adapters.email_adapter.EmailInboundAdapter` |
| `generic_webhook` | HMAC-SHA256 signed JSON envelope | `channel_ingress.adapters.generic_webhook.GenericSignedWebhookAdapter` |

**Voice is deliberately deferred.** The roadmap listed it as optional; the
canonical-message/adapter boundary already accommodates a future voice
adapter (transcript in, `CanonicalInboundMessage` out, same
Conversation/Message/orchestration runtime) with no redesign, but building
a fake adapter purely for appearance — with no real transcript source, no
real telephony webhook, and nothing to verify it against — would provide no
genuine coverage. It is out of scope for this phase.

## Channel adapter protocol

`channel_ingress.adapters.base.ChannelAdapter` is a `Protocol` with three
steps, always in this order:

1. `verify_signature(endpoint, raw_body, headers)` — authenticate the
   transport delivery before anything parsed is trusted. Raises a typed
   `ChannelIngressError` subclass; never returns a boolean.
2. `parse_event(raw_body)` — bounded, non-recursive JSON parsing only. No
   custom XML/YAML/pickle deserialization.
3. `normalize(endpoint, parsed)` — maps the parsed structure onto
   `CanonicalInboundMessage`. Provider-specific field names terminate here.

`EmailInboundAdapter` reuses `GenericSignedWebhookAdapter`'s signature
verification and JSON parsing, overriding only the envelope's identity
field (`from` vs. `external_id`) and HTML handling. A real vendor SDK
adapter is a later, additive implementation behind the same protocol —
nothing else changes to add one.

## Web-chat session model

Web chat never uses the signed-adapter path — HMAC makes no sense for a
public, unauthenticated browser client. Instead:

- `ChatSessionBootstrapView` (public) creates a `ChatSession` row and
  returns a server-generated, cryptographically random token
  (`secrets.token_urlsafe(32)`) **exactly once**.
- Only `sha256(token)` is ever persisted (`ChatSession.token_hash`, unique).
  The plaintext token is never logged, stored again, or returned by any
  other endpoint.
- Every subsequent request (`ChatMessageListCreateView`) resolves the
  session by hashing the caller-supplied token and doing a plain equality
  lookup on the hash — there is nothing to timing-attack, since the hash
  itself is the indexed key, not a secret compared byte-by-byte.
- A session's `external_identity` for customer-identity resolution is its
  own server-generated `ChatSession.id` — never a client-supplied
  "customer_id". A public caller can never claim to be an arbitrary
  existing customer or another session.
- A `ChannelEndpoint.id` (the public widget-routing identifier) selects
  *which* endpoint configuration a session bootstraps against; it is never
  itself sufficient authorization to reach another workspace's data.

## Signature verification

`channel_ingress.security.verify_inbound_signature` — a distinct module
from `webhooks.signing` (which signs *outbound* deliveries): same proven
construction (`HMAC-SHA256(secret, f"{timestamp}." + raw_body)`), applied to
the opposite trust direction.

- `hmac.compare_digest` for constant-time comparison.
- Bounded timestamp freshness (`CHANNELS_SIGNATURE_MAX_PAST_SKEW_SECONDS` /
  `..._FUTURE_SKEW_SECONDS`), independent of provider-event deduplication —
  freshness alone never conflates "fresh" with "not-a-duplicate", and dedup
  alone never conflates "not-a-duplicate" with "recently-signed".
- Every rejection path — missing signature, missing timestamp, malformed
  encoding, expired timestamp, wrong digest — surfaces as one of two public
  outcomes (`signature_invalid` / `signature_expired`); the caller can never
  distinguish *why* a request failed beyond that.
- Body size is bounded (`CHANNELS_MAX_INBOUND_BODY_BYTES`) before any
  parsing is attempted.

Each `ChannelEndpoint`'s signing secret is stored the same way
`WebhookEndpoint` stores its own — an encrypted envelope via
`integrations.crypto`, never plaintext, never returned by any read
endpoint. `POST .../rotate-secret/` is the only way to see a new plaintext
value, once.

## Event deduplication

`InboundChannelEvent` is the durable dedupe/state-machine row (section 9):

- **Dedupe key**: DB-unique `(endpoint, provider_event_id)`. `endpoint`
  already scopes by workspace, channel, and provider, so this one
  constraint is the full "workspace/channel-endpoint + provider +
  provider_event_id" boundary.
- **Idempotent duplicate**: same key, same `payload_digest` (a SHA-256
  digest of the canonical raw bytes — never the bytes themselves) → returns
  the existing row.
- **Idempotency conflict**: same key, different digest → `idempotency_conflict`,
  a caller/provider bug, never silently accepted.
- Web chat uses the same mechanism: its `provider_event_id` is the
  client-supplied `client_message_id`, namespaced by session
  (`f"{session.id}:{client_message_id}"`) so two different sessions can
  never collide on one idempotency slot.

Lifecycle: `received -> processing -> {processed, failed}`. Transitions are
service-only (`channel_ingress.services`); there is no API for a client to
mutate ingress processing state directly.

## Identity resolution

`channel_ingress.identity.resolve_customer_identity` is the single place a
canonical channel identity becomes a workspace-scoped `Customer`. It never
does a bare email search that could match more than one record: every
lookup is a single deterministic key,
`Customer.external_id = f"{channel}:{external_identity}"`, namespaced by
channel so the same raw string from two different channels can never
collide on one customer. An unknown identity is created or rejected per
`ChannelEndpoint.unknown_customer_policy` — never a per-adapter decision. A
signed envelope authenticates the *provider delivery*, never that a `from`
address is a verified identity belonging to a specific existing customer
(section 25) — there is no automatic cross-channel account linking.

## Conversation / thread resolution

`channel_ingress.conversation_resolution.resolve_conversation` maps a
provider thread reference onto `Conversation.external_id`, namespaced by
`ChannelEndpoint.id` (`f"{endpoint.id}:{provider_thread_id}"`) so the same
raw thread id from two different endpoints never merges. Identity and
threading are deliberately separate problems: the same sender messaging
about two unrelated things never gets forced into one conversation. Reopening
a closed conversation on a new inbound message is handled automatically by
the existing `conversations.services.create_inbound_message` reopen branch
— never manipulated here.

## Async processing and recovery

```
request verified -> InboundChannelEvent persisted -> transaction commits
    -> Celery dispatch (transaction.on_commit)
    -> HTTP 202 Accepted
    -> worker claims event, resolves identity/conversation/message
    -> agents.orchestration.start_support_agent_run (existing seam)
```

The actual agent execution dispatch is unchanged Phase 9 machinery:
`start_support_agent_run` calls `agents.services.create_agent_run`, whose
own `transaction.on_commit` schedules `execute_agent_run_task` — this app
never re-implements that dispatch.

**Delivery guarantee**: durable at-least-once processing of an
authenticated inbound provider event, with application-level deduplication
preventing duplicate logical Message/orchestration creation. Not exactly-once
distributed delivery — that guarantee does not exist for this class of
system.

**Broker-publish-gap recovery**: `channel_ingress.recovery.recover_stuck_inbound_events`
(Celery Beat, `CHANNELS_INBOUND_SWEEP_INTERVAL_SECONDS`) re-publishes any
`InboundChannelEvent` still `RECEIVED` past `CHANNELS_INBOUND_SWEEP_STALE_SECONDS`
— mirrors `notifications.recovery` exactly. All correctness comes from the
transactional claim in `claim_inbound_channel_event`, never from the sweep
itself; re-publishing the same event id from two concurrent sweeps, or a
sweep racing an active worker, is always safe.

**Concurrency**: proven with real PostgreSQL row locks and threads
(`channel_ingress/tests/test_concurrency.py`) — two HTTP deliveries of the
same event, two workers racing the same event, and duplicate task
redelivery all converge on exactly one logical `InboundChannelEvent`, one
`Message`, one `AgentRun`.

## Response routing

An agent's customer-visible reply is a `Message`, created by the same
Phase 9 completion path (`agents.services._complete_run` /
`_complete_run_as_handoff`) every conversation-triggered run already uses.
That path now also calls `_schedule_channel_response_routing`, an
`on_commit`-scheduled, fail-open hook into
`channel_ingress.response_delivery.route_channel_response`.

- **Web chat**: no external delivery. The `Message` itself is the
  authoritative, retrievable response — the client polls
  `GET .../webchat/session/<token>/messages/`.
- **Email**: `route_channel_response` creates a `ChannelResponseDelivery`
  (a `notifications.Delivery` companion, mirroring `NotificationDelivery`
  exactly but keyed by the output `Message` instead of a `ToolExecution`)
  and reuses the entire Phase 10 durable delivery engine — claim/attempt/
  backoff/retry, `integrations.services.send_notification`, observability —
  unchanged. No second retry/backoff implementation was created.
- **Generic webhook**: inbound-only in this phase; no concrete outbound
  delivery mechanism is defined for an arbitrary future provider yet.

**Critical invariant** (proven in
`test_response_routing_reuses_the_durable_delivery_engine_not_a_second_run`):
agent execution and response delivery are distinct persisted operations. A
delivery-attempt retry after a successful run never re-runs the agent —
retrying only ever re-attempts the `Delivery`.

The routing destination (`ChannelResponseDelivery.destination_address`) is
read from the resolved `Customer.email`, authoritative server-side state —
never a client/provider-controlled metadata field taken as a routing
credential (section 42).

## Security boundaries

Three deliberately distinct boundaries (section 44-45):

- **Channel configuration** (`workspaces/<id>/channels/endpoints/...`) —
  normal staff JWT + workspace RBAC (`support_manager`/`admin`/`owner` to
  mutate, any member to read secret-free data), exactly like
  `webhooks.permissions`.
- **Provider ingress** (`channels/public/inbound/<endpoint_id>/`) —
  endpoint routing identity + HMAC signature + event dedup. Never staff
  JWT.
- **Web chat** (`channels/public/webchat/...`) — its own bounded
  session-capability model. Never staff JWT, never HMAC.

Cross-workspace access is 404, not 403, throughout — a foreign endpoint id
never confirms its own existence.

## Privacy

Never persisted: authorization headers, raw signatures, provider
credentials, arbitrary headers, cookies, access tokens. Only a SHA-256
digest of the canonical raw bytes is stored for dedupe/conflict detection.
Prometheus labels and trace-span attributes are bounded, code-owned enum
values only (`channel`, `outcome`) — never a workspace/customer/
conversation/message/provider-event id, session token, email, or phone
number (verified directly in `channel_ingress/tests/test_privacy.py` via a
unique-marker sweep of rendered metrics text and API error responses).

## Failure taxonomy

`channel_ingress.errors` — every failure this app can produce maps to
exactly one stable code, never a raw exception class/message:

`signature_invalid` · `signature_expired` · `payload_invalid` ·
`payload_too_large` · `idempotency_conflict` · `identity_not_found` ·
`identity_ambiguous` (structurally unreachable — identity resolution has no
ambiguous-match branch by construction) · `endpoint_disabled` ·
`unsupported_event` · `session_invalid` · `orchestration_failed` ·
`response_route_failed` · `processing_failed`.

## Observability

`supportpilot_channel_ingress_total{channel}`,
`supportpilot_channel_ingress_processing_seconds{channel,outcome}`,
`supportpilot_channel_ingress_duplicates_total{channel}`,
`supportpilot_channel_signature_failures_total{channel}` — all bounded
labels, defined in `observability/metrics.py` alongside every other
domain's metrics. Spans: `channel.ingress`, `channel.response_route` via
the existing `observability.tracing.domain_span` helper. Telemetry failure
never blocks a valid request (proven by dedicated fail-open tests).
