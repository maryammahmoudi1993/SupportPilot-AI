"use client";

import { useId, useState } from "react";

import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  ASSIGNABLE_ROLES,
  canManageTargetRole,
  workspaceRoleLabel,
  type WorkspaceRoleValue,
} from "@/features/workspace-admin/types";
import type { ApiError } from "@/lib/api/errors";

/** Role changes into/out of `admin` grant or remove member-management and
 * workspace-settings capability (backend/workspaces/permissions.py
 * `MEMBER_MANAGEMENT_ROLES`/`WORKSPACE_SETTINGS_ROLES`) — a meaningful
 * enough consequence to confirm explicitly (master prompt Part F §22).
 * Moves among the three non-manage roles (support_manager/support_agent/
 * viewer) are not confirmed — over-confirming a harmless edit is its own
 * usability defect. */
function isEscalationOrReduction(oldRole: string, newRole: string): boolean {
  return oldRole === "admin" || newRole === "admin";
}

/**
 * Renders a membership row's role as plain text, plus — only when the
 * signed-in caller may manage this specific target (backend/workspaces/
 * permissions.py `can_manage_target_role`, mirrored in types.ts) — an
 * editable role control. Never renders a control for the owner role, for a
 * caller without member-management permission at all, or for a target the
 * caller specifically may not manage (an admin managing another admin, or
 * anyone managing themselves as owner/admin — the same rule, not a special
 * case).
 */
export function MemberRoleCell({
  currentRole,
  actorRole,
  isSelf,
  onChangeRole,
  isPending,
  error,
}: {
  currentRole: string;
  actorRole: string | undefined;
  isSelf: boolean;
  onChangeRole: (role: Exclude<WorkspaceRoleValue, "owner">) => void;
  isPending: boolean;
  error: ApiError | null;
}) {
  const selectId = useId();
  const [pendingRole, setPendingRole] = useState<Exclude<WorkspaceRoleValue, "owner"> | null>(null);

  const canEdit = currentRole !== "owner" && canManageTargetRole(actorRole, currentRole) && !isSelf;

  if (!canEdit) {
    return (
      <span>
        {workspaceRoleLabel(currentRole)}
        {isSelf && <span className="text-text-secondary ml-1 text-xs">(You)</span>}
      </span>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={selectId} className="sr-only">
        Role for this member
      </label>
      <select
        id={selectId}
        className="border-border-default bg-surface-0 text-text-primary h-8 rounded-md border px-2 text-sm disabled:opacity-50"
        value={currentRole}
        disabled={isPending}
        aria-busy={isPending || undefined}
        onChange={(event) => {
          const nextRole = event.target.value as Exclude<WorkspaceRoleValue, "owner">;
          if (nextRole === currentRole) {
            return;
          }
          if (isEscalationOrReduction(currentRole, nextRole)) {
            setPendingRole(nextRole);
            return;
          }
          onChangeRole(nextRole);
        }}
      >
        {ASSIGNABLE_ROLES.filter(
          (role) => role === currentRole || canManageTargetRole(actorRole, role),
        ).map((role) => (
          <option key={role} value={role}>
            {workspaceRoleLabel(role)}
          </option>
        ))}
      </select>
      {error && (
        <p role="alert" className="text-danger-700 text-xs">
          {error.message}
        </p>
      )}

      <ConfirmDialog
        open={pendingRole !== null}
        onOpenChange={(open) => {
          if (!open) setPendingRole(null);
        }}
        title={pendingRole === "admin" ? "Grant admin access?" : "Remove admin access?"}
        description={
          pendingRole === "admin"
            ? "This member will be able to manage workspace members and settings."
            : "This member will lose the ability to manage workspace members and settings."
        }
        confirmLabel={pendingRole === "admin" ? "Grant admin" : "Remove admin"}
        confirmVariant={pendingRole === "admin" ? "primary" : "danger"}
        isConfirming={isPending}
        onConfirm={() => {
          if (pendingRole) {
            onChangeRole(pendingRole);
            setPendingRole(null);
          }
        }}
      />
    </div>
  );
}
