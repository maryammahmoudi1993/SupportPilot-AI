# Authentication, Tenancy, and RBAC

This document describes the security model introduced in Phase 2: authentication
lifecycle, workspace tenancy, and role-based access control. Every later domain
(customers, conversations, tickets, knowledge, agents, tools, policies, approvals)
builds on these primitives rather than re-implementing them.

## Authentication lifecycle

Authentication uses JSON Web Tokens issued by
[djangorestframework-simplejwt](https://django-rest-framework-simplejwt.readthedocs.io/).
No custom cryptographic token implementation is used.

- **Access token** — lifetime 15 minutes. Returned in the JSON body of a successful
  login/refresh and sent by the client as `Authorization: Bearer <token>`. It
  identifies the user only; it never carries a workspace-role claim.
- **Refresh token** — lifetime 7 days. Stored exclusively in an `HttpOnly` cookie
  (`AUTH_REFRESH_COOKIE_NAME`, default `sp_refresh_token`), scoped to the
  `/api/v1/auth/` path (`AUTH_REFRESH_COOKIE_PATH`). It is never present in a JSON
  response body.

### Why access and refresh tokens are stored differently

The access token is short-lived and safe to keep in frontend memory, where an XSS
bug would only expose a token that expires within minutes. The refresh token is
long-lived and higher value, so it is kept out of reach of JavaScript entirely via
`HttpOnly`, which trades an XSS-theft risk for a CSRF risk — addressed below.

### Refresh rotation and revocation

Every refresh request rotates the token: `SIMPLE_JWT["ROTATE_REFRESH_TOKENS"]` and
`SIMPLE_JWT["BLACKLIST_AFTER_ROTATION"]` are both enabled, backed by
`rest_framework_simplejwt.token_blacklist`. The token used in a refresh call is
blacklisted the moment a new one is issued — reusing a rotated-away refresh token
fails immediately. Logout blacklists the current refresh token and clears the
cookie; it is deliberately idempotent (a missing or already-invalid token is a
safe no-op) since a browser cannot know whether a previous logout already
succeeded.

## CSRF strategy

DRF's `APIView` is CSRF-exempt from Django's `CsrfViewMiddleware` by default —
that exemption only relaxes when a view authenticates through
`SessionAuthentication`. Because `login`, `refresh`, and `logout` all mutate or
rely on a browser cookie, they call `common.csrf.enforce_csrf(request)`
explicitly, which reimplements the same double-submit check DRF's
`SessionAuthentication.enforce_csrf` performs.

Browser flow:

1. `GET /api/v1/auth/csrf/` primes the `CSRF_COOKIE_NAME` (`sp_csrftoken`) cookie.
2. The frontend reads that cookie and sends it back as the `X-CSRFToken` header
   on `login`, `refresh`, and `logout`.
3. A missing or mismatched header is rejected with `403`.

`CORS_ALLOW_CREDENTIALS = True` only for the explicitly configured
`CORS_ALLOWED_ORIGINS` — no wildcard origin is ever enabled, since combining a
wildcard origin with credentials would defeat the whole cookie-based design.
`CSRF_TRUSTED_ORIGINS` is likewise explicit and environment-driven.

## Workspace as the tenant boundary

`Workspace` is the sole tenant boundary. `WorkspaceMembership` is the sole source
of truth for a user's authorization inside a workspace — never a JWT claim,
request header, query parameter, or other client-supplied state. Every
workspace-scoped request re-derives the caller's membership from the database:

```text
authenticated user -> tenant-scoped selector -> real WorkspaceMembership row
    -> server-side capability check -> workspace-scoped object lookup
    -> service-layer business rule
```

This is what makes role changes and removals take effect on the very next
request, even while a still-valid access token is in the client's hands — there
is no cached or frozen authorization state to go stale.

## Roles

`owner`, `admin`, `support_manager`, `support_agent`, `viewer`. Capability checks
(`workspaces/permissions.py`) are explicit per role rather than a numeric
hierarchy comparison, so future non-hierarchical permissions remain easy to add.
`is_staff`/`is_superuser` are platform-administration concepts and are never used
as workspace roles.

Summary of Phase-2 administration capabilities:

| Capability | Owner | Admin | Others |
|---|---:|---:|---:|
| View workspace / list members | Yes | Yes | Yes |
| Update workspace settings | Yes | Yes | No |
| Add/remove support_manager, support_agent, viewer | Yes | Yes | No |
| Promote/demote an admin | Yes | No | No |
| Manage another admin | Yes | No | No |
| Transfer ownership | Yes | No | No |

## 401 vs 403 vs 404

- **401** — no valid access credentials at all.
- **403** — authenticated, and an active member of the workspace, but the role
  lacks the required capability.
- **404** — the workspace/membership either does not exist, *or* the caller is
  not an active member of it. These two cases are made deliberately
  indistinguishable.

### Why cross-tenant lookups return 404, not 403

A `403` on a workspace ID the caller doesn't belong to confirms that the ID is a
real workspace — an existence leak. Every tenant-scoped selector
(`workspaces/selectors.py`) filters by `memberships__user` *before* resolving the
object, so a member of Workspace B requesting a Workspace A resource by valid
UUID gets exactly the same response as requesting a UUID that was never
allocated at all.

## Ownership-transfer invariant

Ownership can only change through `workspaces.services.transfer_workspace_ownership`,
never through the generic member-role-update endpoint. The service:

- requires the caller to currently be the owner;
- requires the target to be an active member of the same workspace;
- rejects self-transfer;
- locks both membership rows with `select_for_update()` (in a stable ID order,
  to avoid deadlocking against a concurrent transfer attempt) before mutating
  either;
- re-checks that the caller is still the owner once locked, so a stale/repeated
  transfer request fails cleanly instead of corrupting state;
- promotes the target to `owner` and demotes the previous owner to `admin`
  atomically.

A database `UniqueConstraint` (conditional on `role="owner" AND is_active=True`)
independently guarantees at most one active owner per workspace; the service
layer guarantees the complementary invariant — a workspace is never left with
zero owners by any supported operation — which the database cannot express on
its own.

## Immediate revocation / demotion

Because authorization is always re-derived from `WorkspaceMembership` on each
request, removing or demoting a member takes effect on their very next
workspace-scoped call, regardless of how much longer their access token remains
valid. This is exercised directly by regression tests
(`workspaces/tests/test_views.py::TestWorkspaceMemberDetail`).

## Audit coverage

`audit.AuditEvent` is append-only: there is no update or delete service, and no
update/delete API. Workspace and membership administration produce one event
each, written in the same database transaction as the mutation:

```text
workspace.created
workspace.updated
workspace.member_added
workspace.member_role_changed
workspace.member_removed
workspace.ownership_transferred
```

Metadata is restricted to safe, structured facts (role names, internal user
IDs) — never emails, passwords, tokens, or Authorization headers.

## Known limitations / deferred items

- No public self-registration, email verification, password reset, or invite-by-
  email flow — deliberately out of scope for this phase.
- No `leave_workspace` self-service endpoint — deferred rather than shipped
  partially.
- Workspace deactivation (`is_active=False` at the workspace level) is modeled
  in the schema but has no service/API path yet; only membership-level
  activation state is exercised in this phase.
- A general audit-list/read API is deferred to the observability/audit phase;
  this phase only guarantees the write path and its invariants.
