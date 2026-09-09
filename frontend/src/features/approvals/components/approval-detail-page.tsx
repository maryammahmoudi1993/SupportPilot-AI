"use client";

import Link from "next/link";
import { useState } from "react";
import type { ReactNode } from "react";

import { ApprovalStatusBadge } from "@/features/approvals/components/approval-badges";
import { useApprovalDetailQuery, useDecideApprovalMutation } from "@/features/approvals/queries";
import { isActionableApprovalStatus, roleSatisfiesRequirement } from "@/features/approvals/types";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { EntityNotFound } from "@/components/support/entity-not-found";
import { ListError } from "@/components/support/list-error";
import { StructuredPayload } from "@/components/support/structured-payload";
import { Timestamp } from "@/components/support/timestamp";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isValidApprovalId(approvalId: string): boolean {
  return UUID_PATTERN.test(approvalId);
}

function ApprovalNotFound() {
  return (
    <EntityNotFound
      title="Approval not found"
      description="This approval request doesn't exist, or isn't available in your active workspace."
      backHref="/app/approvals"
      backLabel="Back to Approvals"
    />
  );
}

function Field({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-text-muted text-xs font-medium uppercase">{label}</dt>
      <dd className="text-text-primary text-sm">{value}</dd>
    </div>
  );
}

function ApprovalDetailContent({
  workspaceId,
  approvalId,
}: {
  workspaceId: string;
  approvalId: string;
}) {
  const workspace = useWorkspace();
  const approvalQuery = useApprovalDetailQuery(workspaceId, approvalId);
  const mutation = useDecideApprovalMutation(workspaceId, approvalId);
  const [comment, setComment] = useState("");

  if (approvalQuery.isPending) {
    return (
      <div className="flex flex-col gap-3" role="status" aria-label="Loading approval">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
        <span className="sr-only">Loading approval</span>
      </div>
    );
  }

  if (approvalQuery.isError) {
    // P20-404-01 (Chunk 3A): the backend now stably codes every real
    // Http404-raised response as `not_found` (common/exceptions.py). This
    // matches the pattern used by every other detail page (Customer,
    // Conversation, Ticket, AgentRun) — see frontend/README.md.
    if (approvalQuery.error.code === "not_found") {
      return <ApprovalNotFound />;
    }
    return (
      <ListError
        message={approvalQuery.error.message}
        onRetry={() => void approvalQuery.refetch()}
        isRetrying={approvalQuery.isFetching}
      />
    );
  }

  const approval = approvalQuery.data;
  const actorRole = workspace.activeWorkspace?.role;
  // A real, already-fetched field (the caller's own current workspace role,
  // from /auth/me/) — never inferred from email/name (master prompt Part D
  // §18). The backend re-derives and re-checks this from the caller's
  // *current* DB membership on every decide call regardless of what this
  // renders (approvals/services.py `decide_approval`) — this only decides
  // whether to *show* the controls, never whether a decision is honored.
  const canDecideByRole = actorRole
    ? roleSatisfiesRequirement(actorRole, approval.required_role)
    : false;
  const isActionable = isActionableApprovalStatus(approval.status);
  const showControls = isActionable && canDecideByRole;
  const showPermissionNote = isActionable && !canDecideByRole;

  function handleDecision(decision: "approve" | "reject") {
    mutation.mutate(
      { decision, comment: comment.trim() || undefined },
      {
        onError: () => {
          // Master prompt Part B §9-10: an already-decided/expired/
          // cancelled/permission-denied response means the real server
          // state has moved on (or was never what this tab assumed) —
          // refetch and let the actual persisted state redraw the page,
          // never trust the stale local view.
          void approvalQuery.refetch();
        },
      },
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Link href="/app/approvals" className="text-primary-700 text-sm hover:underline">
          ← Back to Approvals
        </Link>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle>{approval.summary}</CardTitle>
            <ApprovalStatusBadge status={approval.status} />
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field
              label="Required role"
              value={
                <span className="capitalize">{approval.required_role.replace(/_/g, " ")}</span>
              }
            />
            <Field label="Requested" value={<Timestamp value={approval.created_at} />} />
            <Field label="Expires" value={<Timestamp value={approval.expires_at} />} />
            <Field
              label="Resolved"
              value={approval.resolved_at ? <Timestamp value={approval.resolved_at} /> : "—"}
            />
          </dl>

          <div>
            <p className="text-text-muted text-xs font-medium uppercase">Frozen action context</p>
            <p className="text-text-secondary mt-1 text-xs">
              The exact, redacted context this decision was made against — never editable, never
              recomputed from the action&rsquo;s current state.
            </p>
            <div className="mt-2">
              <StructuredPayload value={approval.safe_context} label="View frozen context" />
            </div>
          </div>

          {approval.decision && (
            <div className="border-border-subtle rounded-md border p-3">
              <p className="text-text-muted text-xs font-medium uppercase">Decision</p>
              <dl className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
                <Field
                  label="Outcome"
                  value={<span className="capitalize">{approval.decision.decision}</span>}
                />
                <Field label="Decided" value={<Timestamp value={approval.decision.created_at} />} />
                {approval.decision.decided_by !== null && (
                  <Field label="Decided by" value={`User #${approval.decision.decided_by}`} />
                )}
                {approval.decision.safe_comment && (
                  <Field label="Comment" value={approval.decision.safe_comment} />
                )}
              </dl>
            </div>
          )}

          {showPermissionNote && (
            <Alert variant="info">
              You do not have permission to decide this approval request. It requires the{" "}
              <span className="font-medium capitalize">
                {approval.required_role.replace(/_/g, " ")}
              </span>{" "}
              role or higher.
            </Alert>
          )}

          {mutation.isError && (
            <Alert variant="danger" title="This decision could not be recorded">
              {mutation.error.message}
            </Alert>
          )}

          {showControls && (
            <div className="flex flex-col gap-3 border-t pt-4">
              <div>
                <Label htmlFor="approval-comment">Comment (optional)</Label>
                <textarea
                  id="approval-comment"
                  value={comment}
                  onChange={(event) => setComment(event.target.value)}
                  disabled={mutation.isPending}
                  maxLength={1000}
                  rows={2}
                  className="bg-surface-0 text-text-primary border-border-default focus-visible:outline-primary-500 mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none disabled:opacity-50"
                />
              </div>
              <div className="flex gap-2">
                <Button
                  variant="primary"
                  onClick={() => handleDecision("approve")}
                  disabled={mutation.isPending}
                  isLoading={mutation.isPending && mutation.variables?.decision === "approve"}
                >
                  Approve
                </Button>
                <Button
                  variant="danger"
                  onClick={() => handleDecision("reject")}
                  disabled={mutation.isPending}
                  isLoading={mutation.isPending && mutation.variables?.decision === "reject"}
                >
                  Reject
                </Button>
              </div>
              {mutation.isPending && (
                <p className="text-text-secondary text-xs" role="status">
                  Recording your decision…
                </p>
              )}
            </div>
          )}

          {approval.status === "approved" && (
            <Alert variant="success">
              This decision has been accepted. The related action may still be completing
              asynchronously — approval is not itself proof the action has finished.
            </Alert>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export function ApprovalDetailPage({ approvalId }: { approvalId: string }) {
  const workspace = useWorkspace();

  if (!isValidApprovalId(approvalId)) {
    return <ApprovalNotFound />;
  }

  if (workspace.status !== "ready" || !workspace.activeWorkspace) {
    return (
      <div className="flex flex-1 items-center justify-center py-16">
        <Spinner label="Loading your workspace" />
      </div>
    );
  }

  return (
    <ApprovalDetailContent workspaceId={workspace.activeWorkspace.id} approvalId={approvalId} />
  );
}
