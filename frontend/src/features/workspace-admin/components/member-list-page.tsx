"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { useAuth } from "@/features/auth/auth-provider";
import { useUpdateWorkspaceMemberRoleMutation } from "@/features/workspace-admin/mutations";
import { useWorkspaceMemberListQuery } from "@/features/workspace-admin/queries";
import {
  canManageMembers,
  type WorkspaceMembership,
  type WorkspaceMemberListParams,
  type WorkspaceRoleValue,
} from "@/features/workspace-admin/types";
import {
  buildWorkspaceMemberListQueryString,
  parseWorkspaceMemberListParams,
} from "@/features/workspace-admin/url-params";
import { MemberRoleCell } from "@/features/workspace-admin/components/member-role-cell";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { ListError } from "@/components/support/list-error";
import { Pagination } from "@/components/support/pagination";
import { Timestamp } from "@/components/support/timestamp";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import type { ApiError } from "@/lib/api/errors";

function MembersListSkeleton() {
  return (
    <div className="flex flex-col gap-2" role="status" aria-label="Loading workspace members">
      {Array.from({ length: 4 }).map((_, index) => (
        <Skeleton key={index} className="h-11 w-full" />
      ))}
      <span className="sr-only">Loading workspace members</span>
    </div>
  );
}

function MemberRow({
  member,
  workspaceId,
  actorRole,
  currentUserId,
}: {
  member: WorkspaceMembership;
  workspaceId: string;
  actorRole: string | undefined;
  currentUserId: number | undefined;
}) {
  const mutation = useUpdateWorkspaceMemberRoleMutation(workspaceId);
  const isSelf = currentUserId !== undefined && member.user.id === currentUserId;
  const rowError: ApiError | null =
    mutation.isError && mutation.variables?.membershipId === member.id ? mutation.error : null;
  const rowPending = mutation.isPending && mutation.variables?.membershipId === member.id;

  return (
    <tr className="hover:bg-surface-2">
      <td className="px-4 py-2.5 font-medium">
        {member.user.display_name}
        <div className="text-text-secondary text-xs">{member.user.email}</div>
      </td>
      <td className="px-4 py-2.5">
        <MemberRoleCell
          currentRole={member.role}
          actorRole={actorRole}
          isSelf={isSelf}
          isPending={rowPending}
          error={rowError}
          onChangeRole={(role: Exclude<WorkspaceRoleValue, "owner">) => {
            mutation.mutate({ membershipId: member.id, role });
          }}
        />
      </td>
      <td className="text-text-secondary px-4 py-2.5">
        <Timestamp value={member.created_at} />
      </td>
    </tr>
  );
}

function MembersListContent({
  workspaceId,
  pathname,
  params,
  actorRole,
  currentUserId,
}: {
  workspaceId: string;
  pathname: string;
  params: WorkspaceMemberListParams;
  actorRole: string | undefined;
  currentUserId: number | undefined;
}) {
  const router = useRouter();
  const query = useWorkspaceMemberListQuery(workspaceId, params);

  function pushParams(next: WorkspaceMemberListParams) {
    router.replace(`${pathname}${buildWorkspaceMemberListQueryString(next)}`, { scroll: false });
  }

  return (
    <div className="flex flex-col gap-6">
      {query.isPending && <MembersListSkeleton />}

      {query.isError && (
        <ListError
          message={query.error.message}
          onRetry={() => void query.refetch()}
          isRetrying={query.isFetching}
        />
      )}

      {query.isSuccess && query.data.results.length === 0 && (
        <div className="border-border-subtle rounded-lg border border-dashed py-16 text-center">
          <p className="text-text-primary text-sm font-medium">No workspace members yet</p>
        </div>
      )}

      {query.isSuccess && query.data.results.length > 0 && (
        <>
          <div className="border-border-subtle overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[640px] text-left text-sm">
              <caption className="sr-only">Members of this workspace and their roles</caption>
              <thead className="bg-surface-2 text-text-secondary text-xs font-medium uppercase">
                <tr>
                  <th scope="col" className="px-4 py-2.5">
                    Member
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Role
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Joined
                  </th>
                </tr>
              </thead>
              <tbody
                className={cn("divide-border-subtle divide-y", query.isFetching && "opacity-60")}
              >
                {query.data.results.map((member) => (
                  <MemberRow
                    key={member.id}
                    member={member}
                    workspaceId={workspaceId}
                    actorRole={actorRole}
                    currentUserId={currentUserId}
                  />
                ))}
              </tbody>
            </table>
          </div>

          <Pagination
            page={params.page}
            hasPrevious={query.data.previous !== null && query.data.previous !== undefined}
            hasNext={query.data.next !== null && query.data.next !== undefined}
            onPrevious={() => pushParams({ ...params, page: Math.max(1, params.page - 1) })}
            onNext={() => pushParams({ ...params, page: params.page + 1 })}
            summary={`Page ${params.page} · ${query.data.count} member${query.data.count === 1 ? "" : "s"} total`}
          />
        </>
      )}
    </div>
  );
}

function MembersListInner() {
  const workspace = useWorkspace();
  const auth = useAuth();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const workspaceId = workspace.activeWorkspace?.id ?? null;
  const params = parseWorkspaceMemberListParams(searchParams);
  const actorRole = workspace.activeWorkspace?.role;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-text-primary text-xl font-semibold">Workspace members</h1>
        <p className="text-text-secondary text-sm">
          {canManageMembers(actorRole)
            ? "Members of this workspace and their roles. Owner/admin can change a non-owner member's role."
            : "Members of this workspace and their roles."}
        </p>
      </div>

      {workspaceId === null ? (
        <MembersListSkeleton />
      ) : (
        <MembersListContent
          workspaceId={workspaceId}
          pathname={pathname}
          params={params}
          actorRole={actorRole}
          currentUserId={auth.user?.id}
        />
      )}
    </div>
  );
}

/**
 * The workspace Members page (`/app/settings/members`, Phase 24 Chunk 1).
 * Invitation/add-member and removal UI are deliberately out of scope for
 * this chunk (see types.ts's module doc comment) — this page only lists
 * real members and, where the signed-in caller has real permission, lets
 * them change a member's role.
 */
export function MembersListPage() {
  const workspace = useWorkspace();

  if (workspace.status !== "ready" || !workspace.activeWorkspace) {
    return (
      <div className="flex flex-1 items-center justify-center py-16">
        <Spinner label="Loading your workspace" />
      </div>
    );
  }

  return (
    <Suspense
      fallback={
        <div className="flex flex-1 items-center justify-center py-16">
          <Spinner label="Loading workspace members" />
        </div>
      }
    >
      <MembersListInner />
    </Suspense>
  );
}
