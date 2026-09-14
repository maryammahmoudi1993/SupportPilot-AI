"use client";

import { useState } from "react";

import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Button } from "@/components/ui/button";
import { canManageMemberRow, workspaceAdminErrorMessage } from "@/features/workspace-admin/types";
import type { ApiError } from "@/lib/api/errors";

/**
 * A "Remove" control for one membership row (Phase 24 Chunk 2), gated by
 * the exact same row-level rule as the role-edit control (`canManageMemberRow`
 * — see types.ts's doc comment: both `change_workspace_member_role` and
 * `remove_workspace_member` call `can_manage_target_role` identically
 * server-side). Never renders for the owner row, for a caller without
 * member-management permission, for another admin (when the caller is only
 * an admin), or for the caller's own row.
 *
 * Removal is always confirmed — unlike a role change, there is no
 * "harmless" removal (master prompt Part F §22 is about not over-confirming
 * *harmless* edits; removing a member is never that).
 */
export function RemoveMemberButton({
  memberDisplayName,
  targetRole,
  actorRole,
  isSelf,
  onRemove,
  isPending,
  error,
}: {
  memberDisplayName: string;
  targetRole: string;
  actorRole: string | undefined;
  isSelf: boolean;
  onRemove: () => void;
  isPending: boolean;
  error: ApiError | null;
}) {
  const [open, setOpen] = useState(false);

  if (!canManageMemberRow(actorRole, targetRole, isSelf)) {
    return null;
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <Button
        variant="secondary"
        size="sm"
        onClick={() => setOpen(true)}
        disabled={isPending}
        aria-label={`Remove ${memberDisplayName} from this workspace`}
      >
        Remove
      </Button>
      {error && (
        <p role="alert" className="text-danger-700 text-xs">
          {workspaceAdminErrorMessage(error)}
        </p>
      )}
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title="Remove this member?"
        description={`${memberDisplayName} will immediately lose access to this workspace. This can be reversed by adding them back later.`}
        confirmLabel="Remove member"
        confirmVariant="danger"
        isConfirming={isPending}
        onConfirm={() => {
          onRemove();
          setOpen(false);
        }}
      />
    </div>
  );
}
