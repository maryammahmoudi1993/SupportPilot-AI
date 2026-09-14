/**
 * Typed API boundary for the workspace-admin domain.
 *
 * Phase 24 Chunk 1: member list + role update. Phase 24 Chunk 2 adds
 * workspace read/update, add-member, and remove-member — see types.ts's
 * module doc comment.
 *
 * Schema gap (Category B, `ordering`/`search` — same shape as
 * integrations' connection-list gap in features/integrations/api.ts): the
 * generated `api_v1_workspaces_members_list` operation types
 * `ordering`/`search`/`page`/`page_size` as query params, but
 * `WorkspaceMemberListCreateView` (backend/workspaces/views.py) declares no
 * `filter_backends` at all — verified directly against the view and its
 * selector (`workspaces/selectors.py get_workspace_members`, always ordered
 * `-created_at, -id`). `ordering` and `search` are schema-only/dead; only
 * `page` is real (DRF's `PageNumberPagination` reads it directly from the
 * request, independent of any filter backend) — this chunk's UI does not
 * expose `page_size`.
 *
 * Schema gap (Category B, create request/response — re-verified for
 * Chunk 2, since this chunk is the one that now exercises it): the
 * generated `api_v1_workspaces_members_create` operation types its request
 * body as `WorkspaceMembership` (the *read* shape) rather than the real
 * request accepted by `MemberAddSerializer` (`email`, `role` only) —
 * verified against workspaces/serializers.py and workspaces/views.py
 * `WorkspaceMemberListCreateView.create`. `addWorkspaceMember` below sends
 * the real shape directly (an explicit, narrow request body), never the
 * generated (wrong) request type.
 */
import { apiClient } from "@/lib/api/client";
import { requestWithTimeout, unwrap, withRequestTimeout } from "@/lib/api/request";
import type {
  AddWorkspaceMemberInput,
  PaginatedWorkspaceMembershipList,
  UpdateWorkspaceInput,
  Workspace,
  WorkspaceMembership,
  WorkspaceMemberListParams,
  WorkspaceRoleValue,
} from "@/features/workspace-admin/types";
import type { components, paths } from "@/types/api";

type AssignableRole = components["schemas"]["MemberRoleUpdateRoleEnum"];

type GeneratedMemberListQuery = NonNullable<
  paths["/api/v1/workspaces/{workspace_id}/members/"]["get"]["parameters"]["query"]
>;

type MemberListQuery = Pick<GeneratedMemberListQuery, "page">;

function toMemberListQuery(params: WorkspaceMemberListParams): MemberListQuery {
  const query: MemberListQuery = {};
  if (params.page > 1) {
    query.page = params.page;
  }
  return query;
}

export function fetchWorkspaceMemberList(
  workspaceId: string,
  params: WorkspaceMemberListParams,
  signal?: AbortSignal,
): Promise<PaginatedWorkspaceMembershipList> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/members/", {
          params: {
            path: { workspace_id: workspaceId },
            query: toMemberListQuery(params),
          },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}

/**
 * `role` is the only mutable field on this endpoint (backend/workspaces/
 * serializers.py `MemberRoleUpdateSerializer`) — the response is the full,
 * updated `WorkspaceMembership`, which the mutation hook writes straight
 * back into the list cache (no separate detail fetch, no N+1).
 */
export function updateWorkspaceMemberRole(
  workspaceId: string,
  membershipId: string,
  role: Exclude<WorkspaceRoleValue, "owner">,
): Promise<WorkspaceMembership> {
  return requestWithTimeout((signal) =>
    apiClient.PATCH("/api/v1/workspaces/{workspace_id}/members/{membership_id}/", {
      params: { path: { workspace_id: workspaceId, membership_id: membershipId } },
      body: { role: role as AssignableRole },
      signal,
    }),
  );
}

// ---------------------------------------------------------------------------
// Phase 24 Chunk 2 — Workspace settings + add/remove member
// ---------------------------------------------------------------------------

export function fetchWorkspaceDetail(
  workspaceId: string,
  signal?: AbortSignal,
): Promise<Workspace> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/", {
          params: { path: { workspace_id: workspaceId } },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}

/** `name` is the only mutable field (backend/workspaces/serializers.py `WorkspaceUpdateSerializer`). */
export function updateWorkspace(
  workspaceId: string,
  input: UpdateWorkspaceInput,
): Promise<Workspace> {
  return requestWithTimeout((signal) =>
    apiClient.PATCH("/api/v1/workspaces/{workspace_id}/", {
      params: { path: { workspace_id: workspaceId } },
      body: { name: input.name },
      signal,
    }),
  );
}

/**
 * Adds an already-existing, active user directly and immediately by exact
 * email (backend/workspaces/services.py `add_workspace_member`) — never an
 * invitation. Sends the real request shape (`email`, `role`) directly, not
 * the generator's incorrect `WorkspaceMembership` request type (see this
 * file's module doc comment).
 */
export function addWorkspaceMember(
  workspaceId: string,
  input: AddWorkspaceMemberInput,
): Promise<WorkspaceMembership> {
  return requestWithTimeout((signal) =>
    apiClient.POST("/api/v1/workspaces/{workspace_id}/members/", {
      params: { path: { workspace_id: workspaceId } },
      // The generated request type is wrong (see module doc comment) — cast
      // to the real, verified request body rather than fight the generator
      // or use `any`.
      body: {
        email: input.email,
        role: input.role,
      } as unknown as components["schemas"]["WorkspaceMembership"],
      signal,
    }),
  );
}

/** Deactivates a membership (`is_active=false`) — history-preserving, not a hard delete (backend/workspaces/services.py `remove_workspace_member`). Real 204 No Content on success. */
export function removeWorkspaceMember(workspaceId: string, membershipId: string): Promise<void> {
  return requestWithTimeout((signal) =>
    apiClient.DELETE("/api/v1/workspaces/{workspace_id}/members/{membership_id}/", {
      params: { path: { workspace_id: workspaceId, membership_id: membershipId } },
      signal,
    }),
  );
}
