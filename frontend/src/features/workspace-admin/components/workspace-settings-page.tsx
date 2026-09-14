"use client";

import { useEffect, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ListError } from "@/components/support/list-error";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Timestamp } from "@/components/support/timestamp";
import { SettingsNav } from "@/features/workspace-admin/components/settings-nav";
import { useUpdateWorkspaceMutation } from "@/features/workspace-admin/mutations";
import { useWorkspaceDetailQuery } from "@/features/workspace-admin/queries";
import { canManageWorkspace, workspaceAdminErrorMessage } from "@/features/workspace-admin/types";
import { useWorkspace } from "@/features/workspace/workspace-provider";

function WorkspaceSettingsSkeleton() {
  return (
    <div className="flex flex-col gap-2" role="status" aria-label="Loading workspace settings">
      <Skeleton className="h-9 w-full max-w-md" />
      <Skeleton className="h-9 w-full max-w-md" />
      <span className="sr-only">Loading workspace settings</span>
    </div>
  );
}

function WorkspaceSettingsForm({
  workspaceId,
  canManage,
}: {
  workspaceId: string;
  canManage: boolean;
}) {
  const query = useWorkspaceDetailQuery(workspaceId);
  const mutation = useUpdateWorkspaceMutation(workspaceId);
  const [name, setName] = useState("");

  // Synchronize the editable field with the authoritative server value
  // whenever it changes (including after a successful save) — the same
  // justified "external system's state" pattern as WorkspaceProvider's own
  // bootstrap effect, not a form the user is mid-edit in being clobbered:
  // this only re-syncs from a genuinely new server value, never overwrites
  // in-flight typing on every render.
  useEffect(() => {
    if (query.data) {
      setName(query.data.name); // eslint-disable-line react-hooks/set-state-in-effect
    }
  }, [query.data]);

  if (query.isPending) {
    return <WorkspaceSettingsSkeleton />;
  }

  if (query.isError) {
    return (
      <ListError
        message={query.error.message}
        onRetry={() => void query.refetch()}
        isRetrying={query.isFetching}
      />
    );
  }

  const workspace = query.data;

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      return;
    }
    mutation.mutate({ name: trimmed });
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex max-w-md flex-col gap-4"
      aria-label="Workspace settings"
    >
      <div>
        <Label htmlFor="workspace-name">Name</Label>
        <Input
          id="workspace-name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          disabled={!canManage || mutation.isPending}
          maxLength={200}
        />
      </div>

      <dl className="text-text-secondary grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        <dt className="font-medium">Slug</dt>
        <dd>{workspace.slug}</dd>
        <dt className="font-medium">Created</dt>
        <dd>
          <Timestamp value={workspace.created_at} />
        </dd>
      </dl>

      {mutation.isSuccess && !mutation.isPending && (
        <Alert variant="success">Workspace name updated.</Alert>
      )}
      {mutation.isError && (
        <Alert variant="danger" title="This workspace could not be updated">
          {workspaceAdminErrorMessage(mutation.error)}
        </Alert>
      )}

      {canManage && (
        <div>
          <Button type="submit" isLoading={mutation.isPending} disabled={mutation.isPending}>
            Save changes
          </Button>
        </div>
      )}
    </form>
  );
}

function WorkspaceSettingsInner() {
  const workspace = useWorkspace();
  const workspaceId = workspace.activeWorkspace?.id ?? null;
  const canManage = canManageWorkspace(workspace.activeWorkspace?.role);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-text-primary text-xl font-semibold">Workspace settings</h1>
        <p className="text-text-secondary text-sm">
          {canManage
            ? "This workspace's name and identity. Owner/admin can rename it."
            : "This workspace's name and identity."}
        </p>
      </div>

      <SettingsNav active="workspace" />

      {workspaceId === null ? (
        <WorkspaceSettingsSkeleton />
      ) : (
        <WorkspaceSettingsForm workspaceId={workspaceId} canManage={canManage} />
      )}
    </div>
  );
}

/** The Workspace settings page (`/app/settings/workspace`, Phase 24 Chunk 2). */
export function WorkspaceSettingsPage() {
  const workspace = useWorkspace();

  if (workspace.status !== "ready" || !workspace.activeWorkspace) {
    return (
      <div className="flex flex-1 items-center justify-center py-16">
        <Spinner label="Loading your workspace" />
      </div>
    );
  }

  return <WorkspaceSettingsInner />;
}
