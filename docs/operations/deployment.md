# Backend Deployment & Operations

Status: describes the backend deployment contract as of Phase 17 Chunk 3.
Production packaging (compose topology, migration ownership, Beat
scheduling, graceful lifecycle, backup/restore) is built and verified
against a real Docker stack. **The final Phase 17 backend acceptance gate
(full authoritative test suite, complete business-domain clean-room
acceptance, final image acceptance, merge preparation) has not run yet** —
nothing in this document should be read as "Phase 17 complete" until that
gate passes.

## Process topology

| Process | Command | Required for |
|---|---|---|
| Migration job (`migrate`) | `python manage.py migrate --noinput` | One-shot, run once per release before web/worker/beat start — see [Migration ownership](#migration-ownership) |
| Web (Gunicorn) | `gunicorn config.wsgi:application --config config/gunicorn_conf.py --bind 0.0.0.0:8000` | Basic web boot |
| Celery worker | `celery -A config worker -l info --concurrency=${CELERY_WORKER_CONCURRENCY:-2}` | Async agent/evaluation/knowledge/notification/webhook/channel-ingress dispatch, plus stuck-run recovery |
| Celery Beat | `celery -A config beat -l info` | Dispatches every scheduled maintenance task below on its own cadence — see [Scheduled maintenance](#scheduled-maintenance-celery-beat) |
| PostgreSQL (pgvector) | — | Every process above; the only authoritative durable store |
| Redis | — | Django cache, Celery broker/result backend, all rate limiting — never authoritative business storage, see [Redis role and persistence](#redis-role-and-persistence) |

Optional, not required to boot:

| Component | Required for |
|---|---|
| OTLP collector | Trace export (`OBSERVABILITY_TRACING_ENABLED`) |
| Prometheus scraper | Scraping `/metrics/` (always available; scraping it is optional) |
| A live LLM/payment/calendar/email provider | Only when the corresponding `*_LIVE_PROVIDERS_ENABLED`-style flag is explicitly on — every normal/CI/demo/production-like-acceptance path uses the deterministic offline providers; verified booting web/worker/beat with zero paid-provider credentials present (Phase 17 Chunk 3) |
| A TLS-terminating reverse proxy | Any real public deployment — see [TLS / reverse-proxy boundary](#tls--reverse-proxy-boundary); not packaged here |

Runtime container: non-root user (`app`), migrations are a deliberate,
separate release step — never run automatically from the `web`/`worker`/
`beat` container `CMD` (see `backend/entrypoint.sh`'s own comment).

## Production-like Compose topology

Two separate Compose files exist, deliberately not merged:

| File | Purpose |
|---|---|
| `docker-compose.yml` | **Development only.** `runserver`, bind-mounted source, `DEBUG=True`, PostgreSQL/Redis published to the host for local tooling convenience. |
| `docker-compose.prod.yml` | **Production-like.** No bind mounts, immutable built image (`supportpilot-backend:${IMAGE_TAG:-latest}`), Gunicorn/Celery only, PostgreSQL/Redis never published to the host, `migrate`/`web`/`worker`/`beat` as distinct services/processes. |

Production-like usage:

```sh
cp .env.production.example .env.production   # fill in real values; never commit this file
docker compose -p supportpilot-prod --env-file .env.production -f docker-compose.prod.yml build
docker compose -p supportpilot-prod --env-file .env.production -f docker-compose.prod.yml up -d db redis
docker compose -p supportpilot-prod --env-file .env.production -f docker-compose.prod.yml run --rm migrate
docker compose -p supportpilot-prod --env-file .env.production -f docker-compose.prod.yml up -d web worker beat
```

`--env-file .env.production` serves two purposes at once, deliberately: it
is the source Compose interpolates `${VAR}` references in
`docker-compose.prod.yml` from (`WEB_PORT`, `IMAGE_TAG`,
`CELERY_WORKER_CONCURRENCY`, the Postgres healthcheck's role name), **and**
— via each service's own `env_file: .env.production` key — the environment
actually injected into each container. Both mechanisms read the exact same
file so there is exactly one place to configure a deployment. Note this
means `env_file:` in `docker-compose.prod.yml` is a **literal path
reference**, not itself affected by `--env-file`; to test against a
different environment file, edit `.env.production` directly or point both
mechanisms at a differently-named file consistently.

A distinct project name (`-p supportpilot-prod`) keeps this stack's
containers, network, and volumes fully separate from the development
stack, even when both are launched from the same directory.

Verified (Phase 17 Chunk 2/3, against a real, isolated Docker stack —
own project name, own named volumes):

- `db`/`redis` carry no `ports:` entry — internal Compose network only.
- `web` is the only host-exposed service (`${WEB_PORT:-8000}`).
- `web`/`worker`/`beat` each `depends_on: migrate: condition:
  service_completed_successfully` plus `db`/`redis: condition:
  service_healthy` — Compose actually runs `migrate` as part of `up -d web
  worker beat` (it is a real dependency, not a step an operator can
  silently skip), and refuses to start any of the three if it fails.
- No service runs more than one process role.

## Migration ownership

`migrate` is the single, explicit migration owner. `web`, `worker`, and
`beat` never run migrations themselves — confirmed by inspecting each
service's `command:` in `docker-compose.prod.yml` (Gunicorn/Celery only)
and by `backend/entrypoint.sh`'s own comment explaining why (concurrent
replicas racing a schema change).

**Failed migration blocks deployment, does not auto-rerun.** Verified
directly (Phase 17 Chunk 3): with PostgreSQL healthy but the configured
target database nonexistent (a realistic configuration-error case, not a
connectivity outage), `migrate` fails non-zero and Compose's dependency
gating refuses to start `web`/`worker`/`beat` at all —
`service "migrate" didn't complete successfully: exit 1`, and `docker
compose ps` showed only `db`/`redis` running, no app containers. This is
the correct operational contract, not a defect:

- **Runtime dependency outage** (DB/Redis temporarily unreachable while a
  process is already running): `web` readiness reflects it and recovers
  automatically once the dependency returns; `worker`/`beat` reconnect to
  Redis automatically (see [Graceful shutdown and restart
  behavior](#graceful-shutdown-and-restart-behavior)) — no operator action
  needed.
- **Deployment-time migration failure**: the deployment remains failed
  until an operator fixes the underlying issue (bad config, schema
  conflict, DB genuinely unreachable) and explicitly reruns:

  ```sh
  docker compose -p supportpilot-prod --env-file .env.production -f docker-compose.prod.yml run --rm migrate
  ```

  Only after that exits 0 should `web`/`worker`/`beat` be started/restarted.
  There is no automatic retry of a failed migration — Compose does not
  invent one, and none is configured here.

Verified fresh-DB (zero→latest), already-current (safe no-op), and an
upgrade-from-a-rolled-back-migration case (simulating a previous-phase
schema) all succeed cleanly; a DB-unavailable case and a
wrong-target-database case both fail non-zero with an actionable,
credential-free error.

## Scheduled maintenance (Celery Beat)

Beat is a distinct, long-lived process — never run inside `web` or
`worker`. Its full schedule is defined in code
(`config/celery.py`'s `app.conf.beat_schedule`):

| Job | Task | Default interval | Independent of staleness threshold? |
|---|---|---|---|
| `expire-stale-approvals` | `approvals.tasks.expire_stale_approvals_task` | 300s (fixed) | N/A — approvals expire on their own `expires_at`, this only catches ones nobody looked at again |
| `dispatch-due-deliveries` | `notifications.tasks.dispatch_due_deliveries_task` | `DELIVERY_SWEEP_INTERVAL_SECONDS` (30s default) | Yes |
| `recover-expired-delivery-claims` | `notifications.tasks.recover_expired_delivery_claims_task` | `DELIVERY_SWEEP_INTERVAL_SECONDS` (30s default) | Yes |
| `recover-stuck-inbound-channel-events` | `channel_ingress.tasks.recover_stuck_inbound_events_task` | `CHANNELS_INBOUND_SWEEP_INTERVAL_SECONDS` (30s default) | Yes |
| `recover-stuck-agent-runs` | `agents.tasks.recover_stuck_agent_runs_task` | `AGENTS_STUCK_RUN_SWEEP_INTERVAL_SECONDS` (300s default) | Yes — vs. `AGENTS_STUCK_RUN_STALE_SECONDS` (3600s default, 1800s floor) |
| `recover-stuck-evaluation-runs` | `evaluations.tasks.recover_stuck_evaluation_runs_task` | `EVALUATIONS_STUCK_RUN_SWEEP_INTERVAL_SECONDS` (300s default) | Yes — vs. `EVALUATIONS_STUCK_RUN_STALE_SECONDS` (3600s default, 1800s floor) |

The last two (Phase 17) close a gap Phase 16 deliberately left open: the
recovery *logic* for stuck `AgentRun`/`EvaluationRun` rows existed
(`agents/recovery.py`, `evaluations/recovery.py`) with no Celery task
wrapper or schedule entry until now.

**How often we inspect is a separate setting from how old something must
be before recovery, by design** — raising a sweep interval only slows
detection; lowering a staleness threshold below its floor is refused at
Django startup. Verified: overriding sweep intervals down to 5s in an
isolated acceptance stack (never a committed default) causes Beat to
dispatch every 5s while the underlying staleness threshold and its 1800s
safety floor are untouched.

**Single-Beat-scheduler is the expected topology for this single-host
Compose deployment.** No leader election is implemented or planned here.
Verified directly (Phase 17 Chunk 3): running two Beat instances
concurrently against the same broker roughly doubles dispatch volume for
every schedule entry with **zero errors and zero state corruption** in
either instance's log — every sweeper this schedule calls is idempotent
(re-checks status/`updated_at` under its own row lock after acquiring it),
so a duplicate dispatch is unnecessary load, never a correctness problem.
Do not run two Beat instances deliberately; if one is ever running
accidentally (e.g. during a rolling deploy), no manual cleanup is needed.

Beat's `PersistentScheduler` writes a local `celerybeat-schedule` file at
its working directory. `docker-compose.prod.yml` never bind-mounts source
into any service, so this file only ever exists inside the immutable
container's own filesystem, never touching the host — confirmed after a
full acceptance run. The development compose does bind-mount `./backend`,
so `celerybeat-schedule`/`celerybeat.pid` are gitignored there too as a
second line of defense.

## Graceful shutdown and restart behavior

Verified directly against a real running production-like stack (Phase 17
Chunk 3), using SIGTERM/SIGKILL and, where an in-flight request/task was
needed, external client-side tooling only (a raw slow-body HTTP client, a
genuine PostgreSQL row lock) — no sleep was added to application code.

**Web (Gunicorn):**
- Idle `SIGTERM`: master logs `Handling signal: term`, both workers exit,
  container exits 0 within ~2s. No `SIGKILL` needed.
- An in-flight request that finishes **within** `WEB_GRACEFUL_TIMEOUT_SECONDS`
  (default 30s): completes normally, its worker then exits cleanly, master
  shuts down after.
- An in-flight request that has **not** finished when
  `WEB_GRACEFUL_TIMEOUT_SECONDS` elapses: the arbiter terminates that
  worker at exactly the configured timeout (no `Worker exiting` log for
  it — a hard stop, by Gunicorn's own design) and the connection drops.
  Report this honestly: a slow client that exceeds the grace period does
  **not** get a graceful response; it gets cut off exactly at the
  configured boundary.
- Restarting `web` alone (`up -d web`) leaves `worker`/`beat`/PostgreSQL
  untouched and does not run migrations (Gunicorn's own command never
  includes `manage.py migrate`); the new instance becomes ready with no
  manual repair.

**Celery worker:**
- Idle `SIGTERM`: `worker: Warm shutdown (MainProcess)`, clean exit.
- An active task, when `SIGTERM` arrives: Celery's warm shutdown logs
  immediately but the worker process does **not** exit until the
  in-flight task actually finishes — verified by holding a genuine
  PostgreSQL row lock the recovery sweeper's own `select_for_update()`
  needed, sending `SIGTERM`, and observing the worker wait out the full
  lock duration before exiting 0. This repository does not set
  `task_acks_late`/`worker_prefetch_multiplier`/
  `task_reject_on_worker_lost` — Celery's defaults apply
  (`acks_late=False`: a task is acknowledged to the broker **before**
  execution, not after). **This is never claimed as exactly-once.**
- Hard loss (`SIGKILL` mid-task, simulating a real crash): the killed
  task's message is already gone from the broker (acked pre-execution) —
  it is **not** redelivered. A row that task was updating (e.g. a
  `RUNNING` `AgentRun`) is left genuinely stuck with no automatic
  self-healing. This is exactly the scenario the stuck-run recovery
  sweepers exist for: verified restarting the worker and explicitly
  invoking `recover_stuck_agent_runs_task` recovers the abandoned row
  (`failed`/`stuck_worker_recovered`) exactly once; a second invocation is
  a safe no-op (0 recovered) — no duplicate side effect, no terminal-state
  regression.
- Broker (Redis) disappears while the worker is running: Celery's
  built-in consumer retry/backoff logs `Cannot connect to redis://...`
  with increasing backoff, no crash. Once Redis returns, the worker logs
  `Connected to redis://...` and resumes processing automatically — no
  restart required.

**Celery Beat:**
- `SIGTERM`: clean exit, no tracked schedule artifact, no source-tree
  mutation.
- Restart: schedule reloads and dispatches again — verified (with a
  sped-up, non-default sweep interval used only for this acceptance
  check) that all three of `recover-stuck-agent-runs`,
  `recover-stuck-evaluation-runs`, and the pre-existing
  `dispatch-due-deliveries` are dispatched, received, and succeed after
  restart.
- Broker outage while Beat is running: same automatic
  reconnect/backoff/resume behavior as the worker, verified directly —
  `beat: Connection error: ...  Trying again in Ns...` then normal
  `Scheduler: Sending due task ...` resumes once Redis returns.

**PostgreSQL:**
- Plain restart (`docker restart`) and full container **recreation** with
  the same named volume (`postgres_data_prod`) both preserve data —
  verified by creating a representative `Workspace`/`Customer`, recording
  their IDs, restarting then separately recreating the container (a
  different container ID each time), and confirming both rows and the
  total row count were unchanged after each. Never delete the named
  volume to observe this — that is a deliberate data-loss operation, not
  a restart.
- `web`'s `/ready/` reflects a sustained DB outage as `503` and recovers
  to `200` automatically once DB returns, with no manual intervention
  (this was proven with a sustained outage during migration-failure
  testing above; a quick plain restart can complete faster than any
  readiness check notices it at all — both are consistent with the same
  underlying mechanism, just different outage durations).
- `worker`/`beat` continue succeeding scheduled/dispatched tasks across a
  DB restart with no visible interruption (Django opens a fresh DB
  connection per use here; there is no long-held connection to go stale).

## Redis role and persistence

Redis here is **never authoritative business data**. PostgreSQL alone is
the durable store for every business record (workspaces, customers,
conversations, agent runs, evaluations, audit events, etc.). Redis backs:

- the Django cache (including the readiness-check round-trip and all rate
  limiting/throttle state) — disposable; losing it degrades throttling
  and cache-hit performance, never correctness of stored data;
- the Celery broker and result backend — operational, in-flight state
  only (queued-but-unconsumed task messages, task results). A Redis reset
  can lose messages that were published but not yet delivered/acked, and
  Celery result backend entries for tasks whose caller still wants the
  return value. It does **not** lose anything already durably written to
  PostgreSQL by a task that already completed, and the stuck-run recovery
  sweepers exist precisely to detect and correct rows left in a
  non-terminal state by exactly this kind of gap.

**Persistence, as actually configured** (`docker-compose.prod.yml`):
`redis:7-alpine`'s own default `save` policy applies (RDB snapshots at
`3600 1`, `300 100`, `60 10000` — i.e. time/change-count thresholds;
`appendonly` is `no`). A graceful shutdown (`SIGTERM`) triggers a
synchronous save before exit, so data written shortly before a plain
restart is typically preserved; data changed *between* a save point and
an abrupt loss is not. As of Phase 17 Chunk 3 this volume is an
**explicitly named** volume (`redis_data_prod:/data`) — earlier it relied
on the Redis image's own implicit anonymous volume, which Compose happens
to reuse across `up --force-recreate` but which has no name to reattach
to after a full `docker compose down` (verified: an anonymous volume is
gone after `down`; the explicitly named one is only gone after `down -v`
or an explicit `docker volume rm`). This is a deliberate, narrow choice —
not full Redis HA, not a durability upgrade beyond RDB's own snapshot
cadence, just making the existing behavior explicit and predictable
instead of an accident of image defaults.

## TLS / reverse-proxy boundary

**No reverse proxy or TLS terminator is packaged in this repository at
any Compose file.** `web` (Gunicorn) is the directly host-exposed process
in `docker-compose.prod.yml`.

- `SECURE_PROXY_SSL_HEADER` and `USE_X_FORWARDED_HOST` are **not set
  anywhere** in `config/settings.py` — Django's safe defaults apply
  (neither `X-Forwarded-Proto` nor `X-Forwarded-Host` is ever trusted).
  Locked in by a Phase 15 regression test
  (`config/tests/test_settings.py::TestForwardedHeaderTrust`) and
  reconfirmed live (Phase 17 Chunk 3) against a running container:
  spoofing `X-Forwarded-Host` or `X-Forwarded-Proto` has no effect on
  request handling, and a request with a disallowed real `Host` header
  plus a spoofed `X-Forwarded-Host` claiming to be allowed still gets
  `400` — the real `Host` header governs, never the forwarded one.
- `SECURE_SSL_REDIRECT` defaults to `True` outside `DEBUG` — verified
  live: with the production default active, a plain HTTP request to
  `/health/` gets a real `301` to `https://...`. This is the correct,
  safe posture for a process that terminates HTTP directly with no proxy
  in front of it.
- **Local production-like acceptance is HTTP-only by necessity** — there
  is no certificate/TLS listener in this Compose topology. `.env.production`
  for local acceptance therefore sets `SECURE_SSL_REDIRECT=False`
  explicitly, the same way CI does (`.github/workflows/backend-ci.yml`).
  **This override is for local acceptance only** — it is not a
  recommendation for any real deployment, and is never the production
  default (an operator would have to explicitly set it, exactly as CI
  explicitly does).
- **Real public deployment**: an operator-managed, TLS-terminating
  reverse proxy or load balancer must sit in front of `web`, terminate
  HTTPS, and forward only sanitized headers. Only if/when such a proxy is
  actually packaged here should `SECURE_PROXY_SSL_HEADER`/
  `USE_X_FORWARDED_HOST`/`DRF_NUM_PROXIES` be enabled, narrowly, to trust
  exactly that proxy's depth — never speculatively. `docker-compose.prod.yml`
  itself is **not** internet-edge complete; it assumes either a direct,
  TLS-terminating `web` process (real cert config, out of this repo's
  scope) or an external proxy added later.

## Health / readiness / metrics

| Endpoint | Versioned | Auth | Checks |
|---|---|---|---|
| `GET /health/` | No | None | Nothing — liveness only, independent of every dependency |
| `GET /ready/` | No | None | PostgreSQL (`ensure_connection`) + the shared Django cache (bounded Redis round-trip) |
| `GET /metrics/` | No | Bearer token (`OBSERVABILITY_METRICS_TOKEN`) | N/A — Prometheus exposition, entirely separate from health/readiness |

Both `/health/` and `/ready/` return `{"status": "healthy"|"ready"}` (200)
or `{"status": "not_ready"}` (503, readiness only) — never a raw
dependency exception, connection string, or credential. Neither ever calls
an external SaaS provider. Verified live (Phase 17 Chunks 2/3) through
sustained PostgreSQL and Redis outages and recoveries.

The stuck-run recovery metric
(`supportpilot_stuck_run_recoveries_total{domain="agent"|"evaluation"}`)
is visible on the Celery worker's own Prometheus exposition port when
`OBSERVABILITY_CELERY_METRICS_ENABLED=True` (off by default) — verified by
triggering a real recovery and scraping the metric directly. It is
low-cardinality: labeled only by `domain`, never by run ID.

## Environment variables

Never commit real values for anything below. `.env.production.example`
carries the full, current, safe-placeholder template — copy it to
`.env.production` (gitignored) and fill in real values for an actual
deployment; that file is also what `docker-compose.prod.yml` reads via
`--env-file`.

### Required production

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Django signing key. **Fails startup outside `DEBUG`** if left at the dev-only placeholder (Phase 17 Chunk 3 fail-fast check — previously silently defaulted). |
| `DEBUG` | Must be `False` outside local development. |
| `ALLOWED_HOSTS` | Comma/list-shaped host allowlist. |
| `DATABASE_URL` | PostgreSQL (pgvector-enabled) connection string. |
| `REDIS_URL` | Celery broker + result backend. |
| `CACHE_URL` | Django cache backend (Redis) — distinct from `REDIS_URL`, typically a different logical DB on the same instance. |
| `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` | Explicit origin allowlists — no wildcard supported or safe. |
| `AUTH_REFRESH_COOKIE_SECURE`, `AUTH_REFRESH_COOKIE_SAMESITE` | Refresh-cookie attributes; `Secure` is forced true automatically outside `DEBUG` regardless of this value. |
| `INTEGRATIONS_CREDENTIAL_ENCRYPTION_KEYS` | Symmetric key(s) encrypting stored integration/channel credentials at rest. |
| `DRF_NUM_PROXIES` | Trusted reverse-proxy depth for DRF throttle client identity. Default `0` — no reverse proxy trusted; see [TLS / reverse-proxy boundary](#tls--reverse-proxy-boundary). |
| `SECURE_SSL_REDIRECT` | Explicit override for Django's HTTP→HTTPS redirect. Default (unset): `True` outside `DEBUG`. See [TLS / reverse-proxy boundary](#tls--reverse-proxy-boundary) for why local acceptance overrides it to `False`. |
| `OBSERVABILITY_METRICS_TOKEN` | Required (fails startup) once `OBSERVABILITY_METRICS_ENABLED` (default `True`) is active outside `DEBUG`. |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | The `db` service's own credentials in `docker-compose.prod.yml` — keep the password in sync with `DATABASE_URL` above; nothing derives one from the other automatically. |

### Optional with safe default

| Variable | Purpose |
|---|---|
| `WEB_CONCURRENCY`, `WEB_TIMEOUT_SECONDS`, `WEB_GRACEFUL_TIMEOUT_SECONDS`, `WEB_KEEPALIVE_SECONDS` | Gunicorn worker count/timeouts (`config/gunicorn_conf.py`) — conservative defaults (3/30/30/5), never derived from a build/dev-host CPU count. |
| `WEB_PORT` | Host port `docker-compose.prod.yml`'s `web` service publishes. Default `8000`. |
| `CELERY_WORKER_CONCURRENCY` | Celery worker concurrency. Default `2`, independent of `WEB_CONCURRENCY`. |
| `IMAGE_TAG` | Tag `docker-compose.prod.yml` resolves the built image to. Default `latest`. |
| `AGENTS_STUCK_RUN_STALE_SECONDS`, `AGENTS_STUCK_RUN_SWEEP_INTERVAL_SECONDS`, `EVALUATIONS_STUCK_RUN_STALE_SECONDS`, `EVALUATIONS_STUCK_RUN_SWEEP_INTERVAL_SECONDS` | See [Scheduled maintenance](#scheduled-maintenance-celery-beat). |
| `OBSERVABILITY_METRICS_ENABLED`, `OBSERVABILITY_SERVICE_NAME` | `/metrics/` exposure/service label. |
| `OBSERVABILITY_TRACING_ENABLED`, `OBSERVABILITY_OTLP_ENDPOINT` | OTLP trace export. |
| `OBSERVABILITY_CELERY_METRICS_ENABLED`, `OBSERVABILITY_CELERY_METRICS_HOST/PORT`, `OBSERVABILITY_CELERY_PROMETHEUS_MULTIPROC_DIR` | Per-worker Prometheus multiprocess metrics. |

None of the above are required to boot; they degrade to "disabled" safely.

### Live-provider optional (opt-in only — never required to boot)

| Variable | Purpose |
|---|---|
| `AGENTS_LLM_PROVIDER`, `AGENTS_OPENAI_API_KEY`, `AGENTS_OPENAI_BASE_URL` | Real LLM provider. Default (`fake`) is the deterministic offline provider every normal path — including CI and production-like acceptance — uses. |
| `INTEGRATIONS_LIVE_PROVIDERS_ENABLED` | Gate for real Stripe/Google Calendar/SMTP calls. Off by default; every test and the demo seed run entirely against deterministic/fake adapters regardless of this flag. |
| `WEBHOOKS_ALLOW_INSECURE_HTTP` | Development-only relaxation of outbound webhook URL validation — never set in production. |

Verified (Phase 17 Chunk 3): `web`, `worker`, and `beat` all boot cleanly
with none of these set and no paid-provider credential present.

### Development/demo only

| Variable | Purpose |
|---|---|
| `SUPPORTPILOT_DEMO_PASSWORD` | Required by `python manage.py seed_demo`; the command refuses to run without it and never logs/prints it. Not consumed anywhere outside that command. |

## Startup-time validation

Django's own `manage.py check` plus explicit fail-fast `ValueError`s in
`config/settings.py` are the startup validation gate:

- `SECRET_KEY` left at its dev-only placeholder outside `DEBUG` — refuses
  to boot (Phase 17 Chunk 3).
- `OBSERVABILITY_METRICS_TOKEN` missing while metrics are enabled outside
  `DEBUG` — refuses to boot.
- A malformed `DATABASE_URL` — Django itself refuses at first DB access
  (`ImproperlyConfigured`).
- `DRF_NUM_PROXIES` negative, or either stuck-run staleness threshold
  below its 1800s floor — refuses to boot.

All verified directly (Phase 17 Chunk 3) against the real production
image: each failure exits non-zero with an actionable, credential-free
message. Optional integrations degrade to "disabled" and never block
boot; no Stripe/Google/OpenAI/SMTP credential is ever required to start
the application or run its test suite.

## Migrations

- `python manage.py makemigrations --check --dry-run` — development-time
  drift check (also run in the Phase 14 static gate); never run
  `makemigrations` automatically in a deployment pipeline.
- `python manage.py migrate` — the actual deployment-time step, run once
  per release before web/worker/beat processes start serving the new
  code, via the dedicated `migrate` Compose service — not from
  application code or any other container's `CMD`. See [Migration
  ownership](#migration-ownership) for the full failure/rerun contract.
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
- **Celery task execution** (Phase 17 Chunk 3): `task_acks_late` is not
  set (Celery default `False`) — a task is acknowledged to the broker
  before it executes, so a hard worker crash mid-task is **not**
  redelivered by the broker. Durability for the specific cases this
  matters (`AgentRun`, `EvaluationRun`) comes from the independent
  stuck-run recovery sweepers, not from Celery redelivery semantics.
  Delivery is never exactly-once here; keep it that way.
- A repository-wide audit (Phase 14, Milestone 4) checked every place this
  guarantee level is named anywhere in the docs. Outside the explicit
  denials above, every remaining occurrence describes an unrelated
  in-process, single-computation guarantee — never delivery across a
  process boundary.

## Backup / restore

Standard PostgreSQL tools only — no custom backup system.

**Backup** (custom format, compressed, restorable selectively):

```sh
docker compose -p supportpilot-prod --env-file .env.production -f docker-compose.prod.yml \
  exec -T db pg_dump -U "$POSTGRES_USER" -Fc -d "$POSTGRES_DB" -f /tmp/backup.dump
docker compose -p supportpilot-prod --env-file .env.production -f docker-compose.prod.yml \
  exec -T db cat /tmp/backup.dump > ./backup-$(date +%Y%m%dT%H%M%S).dump
```

Pass the password via `PGPASSWORD`/`.pgpass`/the container's own
environment — never as a `-p`/inline CLI argument, which would leak it
into shell history and process listings.

**Restore** (into a separate, empty database — never over the source):

```sh
docker compose -p supportpilot-prod --env-file .env.production -f docker-compose.prod.yml \
  exec -T db psql -U "$POSTGRES_USER" -c "CREATE DATABASE restore_target;"
docker compose -p supportpilot-prod --env-file .env.production -f docker-compose.prod.yml \
  exec -T db pg_restore -U "$POSTGRES_USER" -d restore_target /tmp/backup.dump
```

A brief consistency note: `pg_dump` takes a transactionally-consistent
snapshot at the moment it starts (default `--no-lock`-free MVCC snapshot,
no explicit downtime required for this dump size/shape); it does not
block normal reads/writes on the source database while running.

Verified end-to-end (Phase 17 Chunk 3): backed up a production-like
database containing representative `Workspace`/`Customer` rows, restored
into a throwaway database, confirmed the migration-history table (78
rows), both workspace names, and the customer email all present and
correct, then dropped the throwaway database and removed the dump file —
the source database was never touched (row count unchanged
before/after).

**Redis is never a backup target** — see [Redis role and
persistence](#redis-role-and-persistence); it holds no durable business
data to back up.

## Deployment sequence

1. Build (or pull) the immutable application image.
2. Provide `.env.production` with real values (never the committed
   example placeholders).
3. Start/confirm `db` and `redis` are healthy.
4. Run the one-shot `migrate` job; **do not proceed if it fails** — see
   [Migration ownership](#migration-ownership).
5. Start/restart `web`.
6. Start/restart `worker`.
7. Start/restart `beat`.
8. Verify `/health/` and `/ready/` both return success.
9. Run a smoke check (e.g. a representative authenticated API call).

## Rollback limitations

- Rolling back the **application image** to a previous tag is possible
  (`IMAGE_TAG` points at any previously-built image).
- **Database schema rollback is not automatic.** Django migrations have
  no built-in "undo the last release" operation here — reverting to an
  older application image after a schema migration has already applied
  can leave the older code running against a newer schema it does not
  understand. An operator must evaluate migration compatibility (does the
  new schema still work with the old code, or does the migration itself
  need a hand-written reverse migration) **before** rolling back the
  image, not after.
- There is no automatic backup restore tied to a rollback — restoring
  from a backup is a separate, deliberate operator action (see
  [Backup / restore](#backup--restore)), not something a rollback
  triggers.

## Maintenance commands (safe, routine)

| Command | Purpose |
|---|---|
| `python manage.py check` | Django system check |
| `python manage.py makemigrations --check --dry-run` | Migration drift check |
| `python manage.py migrate` | Apply migrations (deployment-time, via the `migrate` service) |
| `python manage.py seed_demo` | Deterministic, idempotent demo data (requires `SUPPORTPILOT_DEMO_PASSWORD`) |
| `python manage.py spectacular --validate --fail-on-warn --file schema.yaml` | OpenAPI schema generation/validation |
| `pip-audit --skip-editable` | Dependency vulnerability audit |
| `pytest` | Backend test suite |
| `GET /health/`, `GET /ready/` | Liveness/readiness probes |

**Not documented here as routine guidance, and never recommended for
production use**: `flush`, a full database reset, or any destructive
bulk-delete operation. `seed_demo` has no `--reset` flag — it is
additive/idempotent only (see its own docstring for the rationale).

## Residual risks (accepted, not defects)

- Single-host Compose is not high availability: one PostgreSQL instance,
  one Redis instance, one intended Beat scheduler.
- HSTS preload and a real TLS certificate/domain are a real-deployment
  decision this repository does not make on an operator's behalf.
- No automated backup scheduling is provided — the runbook above is
  manual/operator-triggered.
- Celery's default `acks_late=False` means a hard worker crash
  mid-task is not broker-redelivered; durability for the cases that
  matter comes from the stuck-run recovery sweepers, not from Celery
  itself — documented, not hidden.

## Boundary with Phase 17

Chunks 1–3 (Beat packaging, production compose/migration/environment
contract, graceful lifecycle/backup/restore/documentation) are complete
and verified against real Docker stacks. The final Phase 17 acceptance
gate — the full authoritative test suite, complete business-domain
clean-room acceptance (auth, tenancy, agents, tools, approvals,
integrations, knowledge, delivery, channel ingress, evaluation), final
image acceptance, and merge preparation — is separate, later work.
