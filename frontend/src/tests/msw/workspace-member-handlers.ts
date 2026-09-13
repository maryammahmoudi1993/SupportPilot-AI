/**
 * Request-level mocks for the workspace-admin domain (Phase 24 Chunk 1),
 * mirroring the real backend contract (backend/workspaces/views.py,
 * workspaces/selectors.py, workspaces/serializers.py, workspaces/services.py
 * `change_workspace_member_role`): workspace-scoped storage, no filter/
 * search/ordering support (list only — see features/workspace-admin/api.ts's
 * schema-gap note), DRF `PageNumberPagination`'s
 * `{count,next,previous,results}` envelope, and the real
 * `can_manage_target_role` capability rule for role updates (never an
 * owner target/value, admin can never manage another admin).
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
  memberListNetworkError: false,
  /** A single mutation-error scenario, applied by the role-update handler when set. */
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

export function resetWorkspaceMemberMockState(): void {
  workspaceMemberMockState.membersByWorkspace = {};
  workspaceMemberMockState.memberListNetworkError = false;
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
          {
            error: {
              code: "validation_error",
              message: "Ownership can only change via ownership transfer.",
            },
          },
          { status: 400 },
        );
      }
      if (target.role === "owner") {
        return HttpResponse.json(
          {
            error: {
              code: "validation_error",
              message: "The owner's role cannot be changed here.",
            },
          },
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
];
