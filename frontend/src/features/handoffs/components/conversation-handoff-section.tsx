"use client";

import Link from "next/link";

import {
  HandoffStatusBadge,
  handoffReasonLabel,
} from "@/features/handoffs/components/handoff-badges";
import { useHandoffsForConversationQuery } from "@/features/handoffs/queries";
import { ListError } from "@/components/support/list-error";
import { Timestamp } from "@/components/support/timestamp";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Compact, real handoff context for one conversation (master prompt Part H
 * §32, Part G §26 option A) — uses the real `conversation` filter
 * (tickets/selectors.py `handoff_list_for_workspace`), never a guessed join.
 * A conversation may have at most one *active* handoff
 * (`handoff_one_active_per_conversation`), but can accumulate several
 * resolved/cancelled ones over time, so this renders the small real list,
 * not a single assumed row.
 */
export function ConversationHandoffSection({
  workspaceId,
  conversationId,
}: {
  workspaceId: string;
  conversationId: string;
}) {
  const query = useHandoffsForConversationQuery(workspaceId, conversationId);

  if (query.isPending) {
    return (
      <div role="status" aria-label="Loading handoff context">
        <Skeleton className="h-10 w-full" />
        <span className="sr-only">Loading handoff context</span>
      </div>
    );
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

  if (query.data.results.length === 0) {
    return <p className="text-text-secondary text-sm">No human handoff for this conversation.</p>;
  }

  return (
    <ul className="flex flex-col gap-2">
      {query.data.results.map((handoff) => (
        <li key={handoff.id} className="border-border-subtle rounded-md border p-3">
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href={`/app/handoffs/${handoff.id}`}
              className="text-primary-700 text-sm font-medium hover:underline focus-visible:underline"
            >
              {handoffReasonLabel(handoff.reason_code)}
            </Link>
            <HandoffStatusBadge status={handoff.status} />
          </div>
          <p className="text-text-secondary mt-1 text-xs">
            <Timestamp value={handoff.created_at} />
            {handoff.assigned_to && ` · Assigned to ${handoff.assigned_to.email}`}
          </p>
        </li>
      ))}
    </ul>
  );
}
