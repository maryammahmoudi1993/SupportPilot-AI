# Backend Deployment & Operations

Status: describes the **current** backend deployment contract as of Phase
14. **Phase 17 still owns final production packaging and backend
acceptance** — nothing in this document should be read as "production
deployment complete."

## Process topology

| Process | Command | Required for |
|---|---|---|
| Web (Gunicorn) | `gunicorn config.wsgi:application --config config/gunicorn_conf.py` | Basic web boot |
| Celery worker | `celery -A config worker -l info` | Async agent/evaluation/knowledge/notification/webhook/channel-ingress dispatch |
| PostgreSQL (pgvector) | — | Every process above |
| Redis | — | Django cache, Celery broker/result backend, all rate limiting |

Optional, not required to boot:

| Component | Required for |
|---|---|
| OTLP collector | Trace export (`OBSERVABILITY_TRACING_ENABLED`) |
| Prometheus scraper | Scraping `/metrics/` (always available; scraping it is optional) |
| A live LLM/payment/calendar/email provider | Only when the corresponding `*_LIVE_PROVIDERS_ENABLED`-style flag is explicitly on — every normal/CI/demo path uses the deterministic offline providers |

**A Celery Beat schedule is fully defined in code** (`config/celery.py`'s
`app.conf.beat_schedule` — a hardcoded dict, not an env-configurable
setting despite the similarly-named `CELERY_BEAT_SCHEDULE` Django setting
namespace): stale-approval expiry, due-delivery dispatch, expired-claim
recovery, and stuck-inbound-event recovery, each on its own cadence.
**No process currently executes that schedule**, though — `docker-compose.yml`
runs `web` and `celery_worker` only, with no `celery -A config beat`
service, verified directly against the compose file (Phase 14 Milestone 5).
So in this repository's current topology, delivery/channel sweeper and
recovery tasks exist as ordinary Celery tasks with a real schedule already
written for them, but are **not self-triggering** — periodic invocation
requires actually running a Beat process (or an external
cron/platform-scheduler calling the same tasks), which is a deployment-time
responsibility, not automatic here. Treat the missing Beat process as a
known operational packaging gap to close before relying on background
recovery in a real deployment (Phase 17 scope), not as documented behavior
to build around — recovery tasks can still be invoked manually/explicitly
in the meantime.

Runtime container: non-root user (`app`), migrations are a deliberate,
separate release step (`python manage.py migrate`) — never run
automatically on container start, to avoid concurrent web/worker replicas
racing a schema change.

## Health / readiness / metrics

| Endpoint | Versioned | Auth | Checks |
|---|---|---|---|
| `GET /health/` | No | None | Nothing — liveness only, independent of every dependency |
| `GET /ready/` | No | None | PostgreSQL (`ensure_connection`) + the shared Django cache (bounded Redis round-trip) |
| `GET /metrics/` | No | Bearer token (`OBSERVABILITY_METRICS_TOKEN`) | N/A — Prometheus exposition, entirely separate from health/readiness |

Both `/health/` and `/ready/` return `{"status": "healthy"|"ready"}` (200)
or `{"status": "not_ready"}` (503, readiness only) — never a raw
dependency exception, connection string, or credential. Neither ever calls
an external SaaS provider. `/metrics/` accidental public exposure was
explicitly re-verified as part of Phase 14 (Milestone 2) and remains
correctly gated.

## Environment variables

Never commit real values for anything in the "required production" or
"optional provider" tables below. Values shown are illustrative shapes,
not real secrets.

### Required production

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Django signing key. Default is a dev-only placeholder — must be overridden in any non-DEBUG environment. |
| `DEBUG` | Must be `False` outside local development. |
| `ALLOWED_HOSTS` | Comma/list-shaped host allowlist. |
| `DATABASE_URL` | PostgreSQL (pgvector-enabled) connection string. |
| `REDIS_URL` | Celery broker + result backend. |
| `CACHE_URL` | Django cache backend (Redis) — distinct from `REDIS_URL`, typically a different logical DB on the same instance. |
| `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` | Explicit origin allowlists — no wildcard supported or safe. |
| `AUTH_REFRESH_COOKIE_SECURE`, `AUTH_REFRESH_COOKIE_SAMESITE` | Refresh-cookie attributes; `Secure` is forced true automatically outside `DEBUG` regardless of this value. |
| `INTEGRATIONS_CREDENTIAL_ENCRYPTION_KEYS` | Symmetric key(s) encrypting stored integration/channel credentials at rest. |
| `DRF_NUM_PROXIES` | Trusted reverse-proxy depth for DRF throttle client identity (`rest_framework.throttling`). Default `0` — matches this deployment's current no-reverse-proxy topology; forwarded-address headers are never trusted, identity is always the direct peer address. Set to the exact number of trusted, header-sanitizing reverse proxies in front of the application if that topology changes — never a permissive/unset value. A negative or non-integer value fails startup rather than silently degrading trust. See `docs/api/frontend-integration.md`'s "Reverse proxy / client identity" section. |

### Required infrastructure

| Variable | Purpose |
|---|---|
| Celery broker/result (`REDIS_URL`, above) | Async dispatch for agents, evaluations, knowledge ingestion, notifications, webhooks, channel ingress. |

### Optional observability

| Variable | Purpose |
|---|---|
| `OBSERVABILITY_METRICS_ENABLED`, `OBSERVABILITY_METRICS_TOKEN` | `/metrics/` exposure + its bearer token. |
| `OBSERVABILITY_TRACING_ENABLED`, `OBSERVABILITY_OTLP_ENDPOINT`, `OBSERVABILITY_SERVICE_NAME` | OTLP trace export. |
| `OBSERVABILITY_CELERY_METRICS_ENABLED`, `OBSERVABILITY_CELERY_METRICS_HOST/PORT`, `OBSERVABILITY_CELERY_PROMETHEUS_MULTIPROC_DIR` | Per-worker Prometheus multiprocess metrics. |

None of the above are required to boot; they degrade to "disabled" safely.

### Optional provider (opt-in only — never required to boot)

| Variable | Purpose |
|---|---|
| `AGENTS_LLM_PROVIDER`, `AGENTS_OPENAI_API_KEY`, `AGENTS_OPENAI_BASE_URL` | Real LLM provider. Default (`fake`) is the deterministic offline provider every normal path — including CI — uses. |
| `INTEGRATIONS_LIVE_PROVIDERS_ENABLED` | Gate for real Stripe/Google Calendar/SMTP calls. Off by default; every test and the demo seed run entirely against deterministic/fake adapters regardless of this flag. |
| `WEBHOOKS_ALLOW_INSECURE_HTTP` | Development-only relaxation of outbound webhook URL validation — never set in production. |

### Development/demo only

| Variable | Purpose |
|---|---|
| `SUPPORTPILOT_DEMO_PASSWORD` | Required by `python manage.py seed_demo`; the command refuses to run without it and never logs/prints it. Not consumed anywhere outside that command. |

## Startup-time validation

Django's own `manage.py check` (run in CI and by this document's
maintenance-command list below) is the current startup validation gate —
required production settings without a safe default (`SECRET_KEY` in
particular) are expected to be supplied by the deployment platform, not
silently defaulted. Optional integrations degrade to "disabled" and never
block boot; no Stripe/Google/OpenAI/SMTP credential is ever required to
start the application or run its test suite.

## Migrations

- `python manage.py makemigrations --check --dry-run` — development-time
  drift check (also run in the Phase 14 static gate); never run
  `makemigrations` automatically in a deployment pipeline.
- `python manage.py migrate` — the actual deployment-time step, run once
  per release before web/worker processes start serving the new code, not
  from application code or a container `CMD`.
- Historical migrations are treated as immutable once merged; a new
  migration is added for schema changes, never an edit to an already-shipped
  one.

## Delivery guarantees (accurate language — do not upgrade)

- **Outbound webhook/notification delivery** (Phase 10): durable
  **at-least-once** delivery with a stable idempotency identity on the
  receiving side — never exactly-once. A receiver observing a timeout
  after the send actually succeeded is an expected, documented ambiguous
  case, not a bug.
- **Inbound multichannel ingress** (Phase 13): durable at-least-once
  **processing** of authenticated inbound events, with logical
  deduplication on `(endpoint, provider_event_id)` — a byte-identical
  redelivery is an idempotent accept, not exactly-once transport.
- A repository-wide audit (Phase 14, Milestone 4) checked every place this
  guarantee level is named anywhere in the docs. Outside the explicit
  denials above, every remaining occurrence describes an unrelated
  in-process, single-computation guarantee (e.g. a trigger message being
  included in context precisely one time) — never delivery across a
  process boundary. Delivery is never exactly-once here; keep it that way.

## Maintenance commands (safe, routine)

| Command | Purpose |
|---|---|
| `python manage.py check` | Django system check |
| `python manage.py makemigrations --check --dry-run` | Migration drift check |
| `python manage.py migrate` | Apply migrations (deployment-time) |
| `python manage.py seed_demo` | Deterministic, idempotent demo data (requires `SUPPORTPILOT_DEMO_PASSWORD`) |
| `python manage.py spectacular --validate --fail-on-warn --file schema.yaml` | OpenAPI schema generation/validation |
| `pip-audit --skip-editable` | Dependency vulnerability audit |
| `pytest` | Backend test suite |
| `GET /health/`, `GET /ready/` | Liveness/readiness probes |

**Not documented here as routine guidance, and never recommended for
production use**: `flush`, a full database reset, or any destructive
bulk-delete operation. `seed_demo` has no `--reset` flag — it is
additive/idempotent only (see its own docstring for the rationale).

## Boundary with Phase 17

This document describes the backend as it exists after Phase 14. Final
production packaging, the production Docker/Kubernetes manifest review,
and formal backend production acceptance are Phase 17 scope and have not
occurred yet.
