"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { useAuth } from "@/features/auth/auth-provider";
import {
  useRemoveWorkspaceMemberMutation,
  useUpdateWorkspaceMemberRoleMutation,
} from "@/features/workspace-admin/mutations";
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
import { AddMemberForm } from "@/features/workspace-admin/components/add-member-form";
import { MemberRoleCell } from "@/features/workspace-admin/components/member-role-cell";
import { RemoveMemberButton } from "@/features/workspace-admin/components/remove-member-button";
import { SettingsNav } from "@/features/workspace-admin/components/settings-nav";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { ListError } from "@/components/support/list-error";
import { Pagination } from "@/components/support/pagination";
import { Timestamp } from "@/components/support/timestamp";
import { Button } from "@/components/ui/button";
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
  const roleMutation = useUpdateWorkspaceMemberRoleMutation(workspaceId);
  const removeMutation = useRemoveWorkspaceMemberMutation(workspaceId);
  const isSelf = currentUserId !== undefined && member.user.id === currentUserId;
  const roleError: ApiError | null =
    roleMutation.isError && roleMutation.variables?.membershipId === member.id
      ? roleMutation.error
      : null;
  const rolePending = roleMutation.isPending && roleMutation.variables?.membershipId === member.id;
  const removeError: ApiError | null =
    removeMutation.isError && removeMutation.variables === member.id ? removeMutation.error : null;
  const removePending = removeMutation.isPending && removeMutation.variables === member.id;

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
          isPending={rolePending}
          error={roleError}
          onChangeRole={(role: Exclude<WorkspaceRoleValue, "owner">) => {
            roleMutation.mutate({ membershipId: member.id, role });
          }}
        />
      </td>
      <td className="text-text-secondary px-4 py-2.5">
        <Timestamp value={member.created_at} />
      </td>
      <td className="px-4 py-2.5">
        <RemoveMemberButton
          memberDisplayName={member.user.display_name}
          targetRole={member.role}
          actorRole={actorRole}
          isSelf={isSelf}
          isPending={removePending}
          error={removeError}
          onRemove={() => removeMutation.mutate(member.id)}
        />
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
  const [showAddForm, setShowAddForm] = useState(false);
  const canManage = canManageMembers(actorRole);

  function pushParams(next: WorkspaceMemberListParams) {
    router.replace(`${pathname}${buildWorkspaceMemberListQueryString(next)}`, { scroll: false });
  }

  return (
    <div className="flex flex-col gap-6">
      {canManage && (
        <div>
          {showAddForm ? (
            <AddMemberForm
              workspaceId={workspaceId}
              actorRole={actorRole}
              onAdded={() => setShowAddForm(false)}
              onCancel={() => setShowAddForm(false)}
            />
          ) : (
            <Button onClick={() => setShowAddForm(true)}>Add member</Button>
          )}
        </div>
      )}

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
                  <th scope="col" className="px-4 py-2.5">
                    <span className="sr-only">Actions</span>
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
            ? "Members of this workspace and their roles. Owner/admin can add, remove, or change a non-owner member's role."
            : "Members of this workspace and their roles."}
        </p>
      </div>

      <SettingsNav active="members" />

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
 * The workspace Members page (`/app/settings/members`). Phase 24 Chunk 1
 * shipped list + role update; Chunk 2 adds add-member (labeled honestly —
 * there is still no invitation concept, see types.ts's module doc comment)
 * and remove-member, both gated by the same real, server-authoritative
 * `can_manage_target_role` rule as role update.
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
