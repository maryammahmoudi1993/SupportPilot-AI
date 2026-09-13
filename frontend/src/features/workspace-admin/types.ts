/**
 * Workspace administration domain types (Phase 24 Chunk 1 — Workspace
 * Members + Roles + Admin Foundation).
 *
 * `WorkspaceMembership` and `MembershipUser` are the real, public entities
 * this chunk implements (backend/workspaces/models.py `WorkspaceMembership`,
 * serialized by backend/workspaces/serializers.py
 * `WorkspaceMembershipSerializer`/`MembershipUserSerializer`). The member
 * list/detail endpoints already existed on `main` before this phase
 * (backend/workspaces/urls.py `member-list`/`member-detail`) — Phase 24
 * Chunk 1 is the first frontend UI built against them.
 *
 * There is no separate "invitation" entity in the real backend contract:
 * `POST /members/` (backend/workspaces/services.py `add_workspace_member`)
 * adds an *already-existing, active* user directly and immediately by exact
 * email — there is no pending/accept lifecycle, no invite token, no
 * revoke/resend. Per the master prompt's explicit Chunk 1 scope (Part C
 * §15: "Defer to later chunks: invitation workflows; member removal unless
 * essential"), this chunk does not build add/remove-member UI — see
 * README.md, "Phase 24 — Workspace Administration" for the full
 * capability classification.
 */
import type { components } from "@/types/api";

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
export function canManageTargetRole(
  actorRole: string | undefined,
  targetRole: string,
): boolean {
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
