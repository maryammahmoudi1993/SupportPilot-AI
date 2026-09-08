/**
 * Workspace domain types.
 *
 * The backend's real shape (`accounts/serializers.py`
 * `WorkspaceMembershipSummarySerializer`, embedded as `Me.workspaces`) is
 * `{ id, name, slug, role }` per membership. `drf-spectacular` cannot infer
 * a `SerializerMethodField`'s contents, so the generated OpenAPI type for
 * `Me.workspaces` is `{ [key: string]: unknown }[]` — see `parse.ts` for how
 * this gap is closed without `any`/`ts-ignore` (runtime narrowing, not a
 * hand-typed cast).
 */

export const WORKSPACE_ROLES = [
  "owner",
  "admin",
  "support_manager",
  "support_agent",
  "viewer",
] as const;

/** Mirrors the backend's `WorkspaceRoleEnum` (workspaces/models.py `WorkspaceRole`). */
export type WorkspaceRole = (typeof WORKSPACE_ROLES)[number];

/** One workspace the current user is an active member of, as returned by `/me/`. */
export interface WorkspaceMembershipSummary {
  id: string;
  name: string;
  slug: string;
  role: WorkspaceRole;
}
