/**
 * Request-level mocks for the workspace-admin domain, mirroring the real
 * backend contract (backend/workspaces/views.py, workspaces/selectors.py,
 * workspaces/serializers.py, workspaces/services.py): workspace-scoped
 * storage, no filter/search/ordering support on the member list (see
 * features/workspace-admin/api.ts's schema-gap note), DRF
 * `PageNumberPagination`'s `{count,next,previous,results}` envelope, and the
 * real `can_manage_target_role` capability rule shared by role update and
 * removal (never an owner target/value, admin can never manage another
 * admin). Phase 24 Chunk 2 adds workspace read/update, add-member (real
 * existing-account-only semantics — never an invitation), and remove-member
 * (soft-delete via `is_active=false`, mirrored here by the same list filter
 * that already excludes inactive rows).
 */
import { HttpResponse, http } from "msw";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface WorkspaceMemberFixture {
  id: string;
  user: { id: number; email: string; display_name: string };
  role: "owner" | "admin" | "support_manager" | "support_agent" | "viewer";
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceFixture {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface KnownUserFixture {
  id: number;
  email: string;
  display_name: string;
  is_active: boolean;
}

export function makeWorkspaceMemberFixture(
  overrides: Partial<WorkspaceMemberFixture> & {
    id: string;
    user: WorkspaceMemberFixture["user"];
    role: WorkspaceMemberFixture["role"];
  },
): WorkspaceMemberFixture {
  return {
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export const workspaceMemberMockState = {
  membersByWorkspace: {} as Record<string, WorkspaceMemberFixture[]>,
  workspacesById: {} as Record<string, WorkspaceFixture>,
  /** Existing, real accounts add-member may resolve by exact email — mirrors `User.objects.filter(email__iexact=..., is_active=True)`. */
  knownUsersByEmail: {} as Record<string, KnownUserFixture>,
  memberListNetworkError: false,
  workspaceDetailNetworkError: false,
  /** A single mutation-error scenario, applied by any mutation handler below when set. */
  mutationError: null as { code: string; message: string; status: number } | null,
  /**
   * The mock server's re-derivation of "the caller's own current active
   * membership role in this workspace" (backend/workspaces/views.py
   * `WorkspaceScopedMixin` re-resolves this from the database on every
   * request — never trusts a client claim). Defaults to "owner" (every
   * role change allowed) so ordinary role-update tests don't need to set
   * this; a test proving the backend denies an unauthorized direct mutation
   * sets it to a lower role first (see workspace-members-list-page.test.tsx,
   * "direct unauthorized API mutation").
   */
  actorRole: "owner" as "owner" | "admin" | "support_manager" | "support_agent" | "viewer",
};

export function seedWorkspaceMembers(workspaceId: string, members: WorkspaceMemberFixture[]): void {
  workspaceMemberMockState.membersByWorkspace[workspaceId] = members;
}

export function seedWorkspaceDetail(workspace: WorkspaceFixture): void {
  workspaceMemberMockState.workspacesById[workspace.id] = workspace;
}

export function seedKnownUser(user: KnownUserFixture): void {
  workspaceMemberMockState.knownUsersByEmail[user.email.toLowerCase()] = user;
}

export function resetWorkspaceMemberMockState(): void {
  workspaceMemberMockState.membersByWorkspace = {};
  workspaceMemberMockState.workspacesById = {};
  workspaceMemberMockState.knownUsersByEmail = {};
  workspaceMemberMockState.memberListNetworkError = false;
  workspaceMemberMockState.workspaceDetailNetworkError = false;
  workspaceMemberMockState.mutationError = null;
  workspaceMemberMockState.actorRole = "owner";
}

function paginate<T>(items: T[], url: URL) {
  const page = Number(url.searchParams.get("page") ?? "1");
  const pageSize = Number(url.searchParams.get("page_size") ?? "50");
  const count = items.length;
  const start = (page - 1) * pageSize;
  const results = items.slice(start, start + pageSize);
  const hasNext = start + pageSize < count;
  const hasPrevious = page > 1;
  const nextUrl = hasNext ? `${url.origin}${url.pathname}?page=${page + 1}` : null;
  const previousUrl = hasPrevious
    ? `${url.origin}${url.pathname}${page - 1 > 1 ? `?page=${page - 1}` : ""}`
    : null;
  return { count, next: nextUrl, previous: previousUrl, results };
}

/**
 * Real shape (verified empirically against the running backend, see
 * features/workspace-admin/types.ts `workspaceAdminErrorMessage`'s doc
 * comment): every field-keyed `ValidationError` `workspaces/services.py`
 * raises produces a generic top-level `message: "Invalid request."` with
 * the real, specific reason only in `details` — never the specific message
 * at the top level directly.
 */
function validationErrorEnvelope(field: string, message: string) {
  return {
    error: { code: "validation_error", message: "Invalid request.", details: { [field]: message } },
  };
}

function canManageTargetRole(actorRole: string, targetRole: string): boolean {
  if (targetRole === "owner") return false;
  if (actorRole === "owner") return true;
  if (actorRole === "admin") return targetRole !== "admin";
  return false;
}

export const workspaceMemberHandlers = [
  http.get(`${BASE}/api/v1/workspaces/:workspaceId/members/`, async ({ request, params }) => {
    if (workspaceMemberMockState.memberListNetworkError) {
      return HttpResponse.error();
    }
    const workspaceId = params.workspaceId as string;
    const url = new URL(request.url);
    const results = (workspaceMemberMockState.membersByWorkspace[workspaceId] ?? []).filter(
      (m) => m.is_active,
    );
    return HttpResponse.json(paginate(results, url));
  }),

  http.get(`${BASE}/api/v1/workspaces/:workspaceId/members/:membershipId/`, async ({ params }) => {
    const workspaceId = params.workspaceId as string;
    const membershipId = params.membershipId as string;
    const member = workspaceMemberMockState.membersByWorkspace[workspaceId]?.find(
      (m) => m.id === membershipId,
    );
    if (!member) {
      return HttpResponse.json(
        { error: { code: "not_found", message: "Membership not found." } },
        { status: 404 },
      );
    }
    return HttpResponse.json(member);
  }),

  http.patch(
    `${BASE}/api/v1/workspaces/:workspaceId/members/:membershipId/`,
    async ({ request, params }) => {
      if (workspaceMemberMockState.mutationError) {
        const { code, message, status } = workspaceMemberMockState.mutationError;
        return HttpResponse.json({ error: { code, message } }, { status });
      }
      const workspaceId = params.workspaceId as string;
      const membershipId = params.membershipId as string;
      const body = (await request.json()) as { role?: string };
      const list = workspaceMemberMockState.membersByWorkspace[workspaceId] ?? [];
      const index = list.findIndex((m) => m.id === membershipId);
      if (index === -1) {
        return HttpResponse.json(
          { error: { code: "not_found", message: "Membership not found." } },
          { status: 404 },
        );
      }
      const target = list[index];
      const actorRole = workspaceMemberMockState.actorRole;
      const newRole = body.role ?? target.role;

      if (newRole === "owner") {
        return HttpResponse.json(
          validationErrorEnvelope("role", "Ownership can only change via ownership transfer."),
          { status: 400 },
        );
      }
      if (target.role === "owner") {
        return HttpResponse.json(
          validationErrorEnvelope("role", "The owner's role cannot be changed here."),
          { status: 400 },
        );
      }
      if (
        !canManageTargetRole(actorRole, newRole) ||
        !canManageTargetRole(actorRole, target.role)
      ) {
        return HttpResponse.json(
          {
            error: {
              code: "permission_denied",
              message: "You do not have permission to manage this member.",
            },
          },
          { status: 403 },
        );
      }

      list[index] = {
        ...target,
        role: newRole as WorkspaceMemberFixture["role"],
        updated_at: "2026-01-02T00:00:00Z",
      };
      return HttpResponse.json(list[index]);
    },
  ),

  // --- Phase 24 Chunk 2: workspace settings + add/remove member ---------

  http.get(`${BASE}/api/v1/workspaces/:workspaceId/`, async ({ params }) => {
    if (workspaceMemberMockState.workspaceDetailNetworkError) {
      return HttpResponse.error();
    }
    const workspaceId = params.workspaceId as string;
    const workspace = workspaceMemberMockState.workspacesById[workspaceId];
    if (!workspace) {
      return HttpResponse.json(
        { error: { code: "not_found", message: "Workspace not found." } },
        { status: 404 },
      );
    }
    return HttpResponse.json(workspace);
  }),

  http.patch(`${BASE}/api/v1/workspaces/:workspaceId/`, async ({ request, params }) => {
    if (workspaceMemberMockState.mutationError) {
      const { code, message, status } = workspaceMemberMockState.mutationError;
      return HttpResponse.json({ error: { code, message } }, { status });
    }
    const workspaceId = params.workspaceId as string;
    const workspace = workspaceMemberMockState.workspacesById[workspaceId];
    if (!workspace) {
      return HttpResponse.json(
        { error: { code: "not_found", message: "Workspace not found." } },
        { status: 404 },
      );
    }
    const body = (await request.json()) as { name?: string };
    const updated: WorkspaceFixture = {
      ...workspace,
      ...(body.name !== undefined ? { name: body.name } : {}),
      updated_at: "2026-01-02T00:00:00Z",
    };
    workspaceMemberMockState.workspacesById[workspaceId] = updated;
    return HttpResponse.json(updated);
  }),

  http.post(`${BASE}/api/v1/workspaces/:workspaceId/members/`, async ({ request, params }) => {
    if (workspaceMemberMockState.mutationError) {
      const { code, message, status } = workspaceMemberMockState.mutationError;
      return HttpResponse.json({ error: { code, message } }, { status });
    }
    const workspaceId = params.workspaceId as string;
    const body = (await request.json()) as { email: string; role: string };
    const actorRole = workspaceMemberMockState.actorRole;

    if (body.role === "owner" || !canManageTargetRole(actorRole, body.role)) {
      return HttpResponse.json(
        {
          error: {
            code: "permission_denied",
            message: "You do not have permission to assign this role.",
          },
        },
        { status: 403 },
      );
    }

    const user = workspaceMemberMockState.knownUsersByEmail[body.email.toLowerCase()];
    if (!user || !user.is_active) {
      // Deliberately generic — mirrors the real backend never revealing
      // whether an account exists (workspaces/services.py add_workspace_member).
      return HttpResponse.json(
        validationErrorEnvelope("email", "This account could not be added to the workspace."),
        { status: 400 },
      );
    }

    const list = workspaceMemberMockState.membersByWorkspace[workspaceId] ?? [];
    const existing = list.find((m) => m.user.id === user.id);
    if (existing?.is_active) {
      return HttpResponse.json(
        {
          error: {
            code: "conflict",
            message: "This user is already a member of the workspace.",
          },
        },
        { status: 409 },
      );
    }

    const membership: WorkspaceMemberFixture = existing
      ? {
          ...existing,
          role: body.role as WorkspaceMemberFixture["role"],
          is_active: true,
          updated_at: "2026-01-02T00:00:00Z",
        }
      : {
          id: `m-added-${Date.now()}-${Math.random().toString(36).slice(2)}`,
          user: { id: user.id, email: user.email, display_name: user.display_name },
          role: body.role as WorkspaceMemberFixture["role"],
          is_active: true,
          created_at: "2026-01-02T00:00:00Z",
          updated_at: "2026-01-02T00:00:00Z",
        };
    const nextList = existing
      ? list.map((m) => (m.id === existing.id ? membership : m))
      : [...list, membership];
    workspaceMemberMockState.membersByWorkspace[workspaceId] = nextList;
    return HttpResponse.json(membership, { status: 201 });
  }),

  http.delete(
    `${BASE}/api/v1/workspaces/:workspaceId/members/:membershipId/`,
    async ({ params }) => {
      if (workspaceMemberMockState.mutationError) {
        const { code, message, status } = workspaceMemberMockState.mutationError;
        return HttpResponse.json({ error: { code, message } }, { status });
      }
      const workspaceId = params.workspaceId as string;
      const membershipId = params.membershipId as string;
      const list = workspaceMemberMockState.membersByWorkspace[workspaceId] ?? [];
      const index = list.findIndex((m) => m.id === membershipId);
      if (index === -1) {
        return HttpResponse.json(
          { error: { code: "not_found", message: "Membership not found." } },
          { status: 404 },
        );
      }
      const target = list[index];
      const actorRole = workspaceMemberMockState.actorRole;

      if (target.role === "owner") {
        return HttpResponse.json(
          validationErrorEnvelope("membership", "The workspace owner cannot be removed."),
          { status: 400 },
        );
      }
      if (!canManageTargetRole(actorRole, target.role)) {
        return HttpResponse.json(
          {
            error: {
              code: "permission_denied",
              message: "You do not have permission to remove this member.",
            },
          },
          { status: 403 },
        );
      }

      list[index] = { ...target, is_active: false, updated_at: "2026-01-02T00:00:00Z" };
      return new HttpResponse(null, { status: 204 });
    },
  ),
];
