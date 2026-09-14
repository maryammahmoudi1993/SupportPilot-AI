/**
 * Workspace administration domain types.
 *
 * Phase 24 Chunk 1 — Workspace Members + Roles + Admin Foundation:
 * `WorkspaceMembership` and `MembershipUser` are the real, public entities
 * (backend/workspaces/models.py `WorkspaceMembership`, serialized by
 * backend/workspaces/serializers.py `WorkspaceMembershipSerializer`/
 * `MembershipUserSerializer`). The member list/detail endpoints already
 * existed on `main` before this phase (backend/workspaces/urls.py
 * `member-list`/`member-detail`) — Phase 24 Chunk 1 was the first frontend
 * UI built against them (list + role update only).
 *
 * Phase 24 Chunk 2 — Workspace Settings + Membership Lifecycle: adds
 * `Workspace` (read/update — backend/workspaces/views.py
 * `WorkspaceDetailView`), add-member (`POST /members/`, backend/workspaces/
 * services.py `add_workspace_member`), and remove-member (`DELETE
 * /members/{id}/`, `remove_workspace_member`) — all re-verified directly
 * against `main` before this chunk, unchanged since Chunk 1's discovery.
 *
 * There is still no separate "invitation" entity in the real backend
 * contract: `POST /members/` adds an *already-existing, active* user
 * directly and immediately by exact email — there is no pending/accept
 * lifecycle, no invite token, no revoke/resend. This chunk's add-member UI
 * is labeled honestly as "Add member", never "Invite" — see README.md,
 * "Phase 24 — Workspace Administration" for the full capability
 * classification.
 */
import type { components } from "@/types/api";

export type Workspace = components["schemas"]["Workspace"];
export type WorkspaceMembership = components["schemas"]["WorkspaceMembership"];
export type MembershipUser = components["schemas"]["MembershipUser"];
export type PaginatedWorkspaceMembershipList =
  components["schemas"]["PaginatedWorkspaceMembershipList"];

/**
 * Full real role enum (backend/workspaces/models.py `WorkspaceRole`) — used
 * for *rendering* every membership's role, including `owner` which can
 * never be assigned through this chunk's role-update control.
 */
export const WORKSPACE_ROLES = [
  "owner",
  "admin",
  "support_manager",
  "support_agent",
  "viewer",
] as const;
export type WorkspaceRoleValue = (typeof WORKSPACE_ROLES)[number];

/**
 * Roles assignable through the generic role-update endpoint (backend/
 * workspaces/serializers.py `ASSIGNABLE_ROLES` / generated
 * `MemberRoleUpdateRoleEnum`) — `owner` is deliberately excluded everywhere
 * here; ownership can only change via the dedicated (out-of-scope for
 * Chunk 1) transfer-ownership endpoint.
 */
export const ASSIGNABLE_ROLES: readonly WorkspaceRoleValue[] = [
  "admin",
  "support_manager",
  "support_agent",
  "viewer",
];

const ROLE_LABELS: Record<WorkspaceRoleValue, string> = {
  owner: "Owner",
  admin: "Admin",
  support_manager: "Support Manager",
  support_agent: "Support Agent",
  viewer: "Viewer",
};

/** Never crashes on a role value this build doesn't recognize — falls back to the raw value, same policy as `IntegrationConnectionStatusBadge`. */
export function workspaceRoleLabel(role: string): string {
  return ROLE_LABELS[role as WorkspaceRoleValue] ?? role;
}

/** Real, backend-tested pagination only (workspaces/selectors.py `get_workspace_members` + `common.pagination.StandardResultsSetPagination`). See api.ts for the `ordering`/`search` schema gap — no filter/search/ordering exists for this list. */
export interface WorkspaceMemberListParams {
  page: number;
}

export const DEFAULT_WORKSPACE_MEMBER_LIST_PARAMS: WorkspaceMemberListParams = {
  page: 1,
};

/**
 * The backend's real member-management roles (backend/workspaces/
 * permissions.py `MEMBER_MANAGEMENT_ROLES` — owner/admin). Mirrored here
 * (not imported — frontend/backend are separate deployables), same pattern
 * as `canManageIntegrations`. Controls whether the role-change control ever
 * renders at all for the signed-in caller.
 */
const MEMBER_MANAGEMENT_ROLES: ReadonlySet<string> = new Set(["owner", "admin"]);

export function canManageMembers(role: string | undefined): boolean {
  return role !== undefined && MEMBER_MANAGEMENT_ROLES.has(role);
}

/**
 * Explicit, non-hierarchical capability check for whether `actorRole` may
 * change a membership currently holding (or being assigned) `targetRole` —
 * mirrored directly from backend/workspaces/permissions.py
 * `can_manage_target_role` (never a numeric/hierarchical comparison):
 * - nobody may use this path to create or modify an owner;
 * - owner may manage any non-owner role, including admin;
 * - admin may manage only roles strictly below admin (never another admin,
 *   including themself — this is what makes self-lockout structurally
 *   impossible without any separate frontend-only "is this me" check: an
 *   admin's own row always has `target_role === "admin"`, which this
 *   function already refuses for an admin actor).
 *
 * The backend is the authoritative decision-maker every time (it re-checks
 * this exact rule server-side on every PATCH) — this mirror only decides
 * whether to *render* an enabled control; it grants no capability of its
 * own.
 */
export function canManageTargetRole(actorRole: string | undefined, targetRole: string): boolean {
  if (targetRole === "owner") {
    return false;
  }
  if (actorRole === "owner") {
    return true;
  }
  if (actorRole === "admin") {
    return targetRole !== "admin";
  }
  return false;
}

/**
 * Shared row-level gate for both the role-edit control (Chunk 1) and the
 * remove-member control (Chunk 2) — both real mutations enforce the exact
 * same `can_manage_target_role` rule server-side (backend/workspaces/
 * services.py `change_workspace_member_role` and `remove_workspace_member`
 * both call it identically), so one frontend function decides whether
 * *either* control renders for a given row. `isSelf` is included defensively
 * (never actually changes the outcome, since an actor's own row's role
 * already makes `canManageTargetRole` return false on its own — see that
 * function's doc comment) so the intent stays explicit at every call site.
 */
export function canManageMemberRow(
  actorRole: string | undefined,
  targetRole: string,
  isSelf: boolean,
): boolean {
  return !isSelf && canManageTargetRole(actorRole, targetRole);
}

// ---------------------------------------------------------------------------
// Phase 24 Chunk 2 — Workspace settings + add/remove member
// ---------------------------------------------------------------------------

/**
 * The backend's real workspace-settings roles (backend/workspaces/
 * permissions.py `CanManageWorkspace.WORKSPACE_SETTINGS_ROLES` — owner/
 * admin, the identical set as `MEMBER_MANAGEMENT_ROLES`, but kept as its own
 * named check since the two backend permission classes are declared
 * separately and could diverge in a future backend change).
 */
const WORKSPACE_SETTINGS_ROLES: ReadonlySet<string> = new Set(["owner", "admin"]);

export function canManageWorkspace(role: string | undefined): boolean {
  return role !== undefined && WORKSPACE_SETTINGS_ROLES.has(role);
}

/** `PATCH /workspaces/{id}/` accepts only `name` (backend/workspaces/serializers.py `WorkspaceUpdateSerializer`). */
export interface UpdateWorkspaceInput {
  name: string;
}

/**
 * `POST /members/` accepts an exact email plus one of the assignable roles
 * (backend/workspaces/serializers.py `MemberAddSerializer` — same
 * `ASSIGNABLE_ROLES` as role update; `owner` is never assignable here
 * either). This is a direct "add an existing, active account" action, never
 * an invitation — see this module's doc comment.
 */
export interface AddWorkspaceMemberInput {
  email: string;
  role: Exclude<WorkspaceRoleValue, "owner">;
}

/**
 * Real discovery (verified empirically against the running backend, not
 * assumed from reading the serializer alone): every `ValidationError`
 * `workspaces/services.py` raises with a field-keyed dict — e.g.
 * `ValidationError({"email": "This account could not be added to the
 * workspace."})`, `{"role": "Ownership can only change via ownership
 * transfer."}`, `{"membership": "The workspace owner cannot be removed."}` —
 * hits DRF's *dict-shaped* exception path, which `common/exceptions.py
 * custom_exception_handler` cannot distinguish from an ordinary serializer
 * field-validation dict. The client-facing envelope's top-level `message` is
 * therefore always the generic "Invalid request." for these — the real,
 * specific, safe reason only exists in `error.details` (e.g.
 * `{"email": "This account could not be added to the workspace."}`).
 * `ConflictError`/`PermissionDenied` raised with a single string (not a
 * dict) are unaffected — those already carry the real message at the top
 * level.
 *
 * This helper renders the real, specific reason whenever one is available,
 * rather than showing every workspace-admin validation failure as the same
 * uninformative "Invalid request." — never invents wording, only unwraps
 * what the server already sent.
 */
export function workspaceAdminErrorMessage(error: {
  code: string;
  message: string;
  details: Record<string, unknown> | undefined;
}): string {
  if (error.code !== "validation_error" || !error.details) {
    return error.message;
  }
  const detailMessages = Object.values(error.details).filter(
    (value): value is string => typeof value === "string" && value.length > 0,
  );
  return detailMessages.length > 0 ? detailMessages.join(" ") : error.message;
}
