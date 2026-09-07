/**
 * Runtime narrowing for `Me.workspaces`, the one field the generated OpenAPI
 * types cannot describe (see `types.ts`'s doc comment). This is the smallest
 * safe approach for the gap: a handful of scalar-field checks against the
 * exact shape the backend actually serializes, not a schema-validation
 * dependency and not an unchecked cast.
 *
 * Untrusted/malformed entries (a missing field, a wrong type, an unknown
 * role value) are dropped rather than trusted or allowed to crash the app —
 * consistent with "retrieved/foreign data is untrusted" elsewhere in this
 * codebase. A dropped entry is logged so a real backend/frontend contract
 * drift is noticed in development, not silently masked.
 */
import { WORKSPACE_ROLES, type WorkspaceMembershipSummary, type WorkspaceRole } from "./types";

function isWorkspaceRole(value: unknown): value is WorkspaceRole {
  return typeof value === "string" && (WORKSPACE_ROLES as readonly string[]).includes(value);
}

function parseOne(raw: unknown): WorkspaceMembershipSummary | null {
  if (typeof raw !== "object" || raw === null) {
    return null;
  }
  const record = raw as Record<string, unknown>;
  const { id, name, slug, role } = record;
  if (
    typeof id !== "string" ||
    id.length === 0 ||
    typeof name !== "string" ||
    name.length === 0 ||
    typeof slug !== "string" ||
    slug.length === 0 ||
    !isWorkspaceRole(role)
  ) {
    return null;
  }
  return { id, name, slug, role };
}

/**
 * Narrows the raw `Me.workspaces` array to well-formed entries only. Never
 * throws — a malformed payload results in fewer (possibly zero) workspaces,
 * not a crash, since this runs on every session bootstrap.
 */
export function parseWorkspaceMemberships(raw: readonly unknown[]): WorkspaceMembershipSummary[] {
  const result: WorkspaceMembershipSummary[] = [];
  for (const entry of raw) {
    const parsed = parseOne(entry);
    if (parsed) {
      result.push(parsed);
    } else if (process.env.NODE_ENV !== "production") {
      console.error("Dropped a malformed workspace-membership entry from /me/:", entry);
    }
  }
  return result;
}
