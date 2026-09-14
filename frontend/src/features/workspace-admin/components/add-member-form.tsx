"use client";

import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAddWorkspaceMemberMutation } from "@/features/workspace-admin/mutations";
import {
  ASSIGNABLE_ROLES,
  canManageTargetRole,
  workspaceAdminErrorMessage,
  workspaceRoleLabel,
  type WorkspaceRoleValue,
} from "@/features/workspace-admin/types";

/**
 * Adds an already-existing, active account to this workspace by exact email
 * (backend/workspaces/services.py `add_workspace_member`) — labeled
 * honestly as "Add member", never "Invite": there is no invitation token,
 * no pending state, no accept step. A nonexistent or inactive account and
 * an already-a-member account are indistinguishable-by-design 400/409
 * responses from the backend (never a client-side email-existence guess);
 * this form renders whatever safe message the server returns, exactly as
 * every other domain's create form does (see features/integrations/
 * components/create-connection-form.tsx).
 */
export function AddMemberForm({
  workspaceId,
  actorRole,
  onAdded,
  onCancel,
}: {
  workspaceId: string;
  actorRole: string | undefined;
  onAdded: () => void;
  onCancel: () => void;
}) {
  const mutation = useAddWorkspaceMemberMutation(workspaceId);
  const assignableRoles: Exclude<WorkspaceRoleValue, "owner">[] = ASSIGNABLE_ROLES.filter((role) =>
    canManageTargetRole(actorRole, role),
  ) as Exclude<WorkspaceRoleValue, "owner">[];
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Exclude<WorkspaceRoleValue, "owner">>(
    assignableRoles[0] ?? "viewer",
  );

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const trimmedEmail = email.trim();
    if (!trimmedEmail) {
      return;
    }
    mutation.mutate(
      { email: trimmedEmail, role },
      {
        onSuccess: () => {
          setEmail("");
          onAdded();
        },
      },
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="border-border-subtle flex max-w-full min-w-0 flex-col gap-4 overflow-x-hidden rounded-lg border p-4"
      aria-label="Add workspace member"
    >
      <div>
        <Label htmlFor="add-member-email">Email</Label>
        <Input
          id="add-member-email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          disabled={mutation.isPending}
          required
          placeholder="person@example.com"
        />
      </div>

      <div>
        <Label htmlFor="add-member-role">Role</Label>
        <select
          id="add-member-role"
          value={role}
          onChange={(event) => setRole(event.target.value as Exclude<WorkspaceRoleValue, "owner">)}
          disabled={mutation.isPending}
          className="bg-surface-0 text-text-primary border-border-default focus-visible:outline-primary-500 h-9 w-full rounded-md border px-3 text-sm outline-none"
        >
          {assignableRoles.map((option) => (
            <option key={option} value={option}>
              {workspaceRoleLabel(option)}
            </option>
          ))}
        </select>
      </div>

      {mutation.isError && (
        <Alert variant="danger" title="This member could not be added">
          {workspaceAdminErrorMessage(mutation.error)}
        </Alert>
      )}

      <div className="flex gap-2">
        <Button type="submit" isLoading={mutation.isPending} disabled={mutation.isPending}>
          Add member
        </Button>
        <Button type="button" variant="secondary" onClick={onCancel} disabled={mutation.isPending}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
