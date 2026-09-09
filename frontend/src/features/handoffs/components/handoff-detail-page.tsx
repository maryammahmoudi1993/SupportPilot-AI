"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import {
  HandoffStatusBadge,
  handoffReasonLabel,
} from "@/features/handoffs/components/handoff-badges";
import { useHandoffDetailQuery } from "@/features/handoffs/queries";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { EntityNotFound } from "@/components/support/entity-not-found";
import { ListError } from "@/components/support/list-error";
import { Timestamp } from "@/components/support/timestamp";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isValidHandoffId(handoffId: string): boolean {
  return UUID_PATTERN.test(handoffId);
}

function HandoffNotFound() {
  return (
    <EntityNotFound
      title="Handoff not found"
      description="This handoff doesn't exist, or isn't available in your active workspace."
      backHref="/app/handoffs"
      backLabel="Back to Handoffs"
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

function HandoffDetailContent({
  workspaceId,
  handoffId,
}: {
  workspaceId: string;
  handoffId: string;
}) {
  const handoffQuery = useHandoffDetailQuery(workspaceId, handoffId);

  if (handoffQuery.isPending) {
    return (
      <div className="flex flex-col gap-3" role="status" aria-label="Loading handoff">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
        <span className="sr-only">Loading handoff</span>
      </div>
    );
  }

  if (handoffQuery.isError) {
    // P20-404-01 (Chunk 3A) — see the matching comment in
    // approval-detail-page.tsx: the backend now stably codes every real
    // Http404-raised response as `not_found`.
    if (handoffQuery.error.code === "not_found") {
      return <HandoffNotFound />;
    }
    return (
      <ListError
        message={handoffQuery.error.message}
        onRetry={() => void handoffQuery.refetch()}
        isRetrying={handoffQuery.isFetching}
      />
    );
  }

  const handoff = handoffQuery.data;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Link href="/app/handoffs" className="text-primary-700 text-sm hover:underline">
          ← Back to Handoffs
        </Link>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle>{handoffReasonLabel(handoff.reason_code)}</CardTitle>
            <HandoffStatusBadge status={handoff.status} />
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field
              label="Conversation"
              value={
                <Link
                  href={`/app/inbox/${handoff.conversation_id}`}
                  className="text-primary-700 hover:underline focus-visible:underline"
                >
                  View conversation
                </Link>
              }
            />
            <Field
              label="Agent run"
              value={
                handoff.agent_run_id ? (
                  <Link
                    href={`/app/agent-runs/${handoff.agent_run_id}`}
                    className="text-primary-700 hover:underline focus-visible:underline"
                  >
                    View agent run
                  </Link>
                ) : (
                  "— (not tied to a run)"
                )
              }
            />
            <Field
              label="Ticket"
              value={
                handoff.ticket_id ? (
                  <Link
                    href={`/app/tickets/${handoff.ticket_id}`}
                    className="text-primary-700 hover:underline focus-visible:underline"
                  >
                    View related ticket
                  </Link>
                ) : (
                  "— (not tied to a ticket)"
                )
              }
            />
            <Field label="Assigned to" value={handoff.assigned_to?.email ?? "Unassigned"} />
            <Field label="Created" value={<Timestamp value={handoff.created_at} />} />
            <Field
              label="Resolved"
              value={handoff.resolved_at ? <Timestamp value={handoff.resolved_at} /> : "—"}
            />
          </dl>

          {handoff.safe_summary && (
            <dl>
              <dt className="text-text-muted text-xs font-medium uppercase">Summary</dt>
              <dd className="text-text-primary mt-1 text-sm break-words whitespace-pre-wrap">
                {handoff.safe_summary}
              </dd>
            </dl>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export function HandoffDetailPage({ handoffId }: { handoffId: string }) {
  const workspace = useWorkspace();

  if (!isValidHandoffId(handoffId)) {
    return <HandoffNotFound />;
  }

  if (workspace.status !== "ready" || !workspace.activeWorkspace) {
    return (
      <div className="flex flex-1 items-center justify-center py-16">
        <Spinner label="Loading your workspace" />
      </div>
    );
  }

  return <HandoffDetailContent workspaceId={workspace.activeWorkspace.id} handoffId={handoffId} />;
}
