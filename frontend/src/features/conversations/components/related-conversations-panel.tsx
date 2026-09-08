"use client";

import Link from "next/link";

import { ConversationStatusBadge } from "@/features/conversations/components/conversation-badges";
import { useConversationListQuery } from "@/features/conversations/queries";
import { DEFAULT_CONVERSATION_LIST_PARAMS } from "@/features/conversations/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

const PREVIEW_COUNT = 5;

/**
 * A bounded, real "related conversations" preview for Customer detail —
 * mirrors features/tickets/components/related-tickets-panel.tsx: a single
 * request using the backend's real `customer` filter (see
 * conversations/selectors.py `conversation_list_for_workspace`), never a
 * per-row fetch.
 */
export function RelatedConversationsPanel({
  workspaceId,
  customerId,
}: {
  workspaceId: string;
  customerId: string;
}) {
  const query = useConversationListQuery(workspaceId, {
    ...DEFAULT_CONVERSATION_LIST_PARAMS,
    customerId,
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Related conversations</CardTitle>
      </CardHeader>
      <CardContent>
        {query.isPending && (
          <div
            className="flex flex-col gap-2"
            role="status"
            aria-label="Loading related conversations"
          >
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
            <span className="sr-only">Loading related conversations</span>
          </div>
        )}

        {query.isError && <p className="text-danger-700 text-sm">{query.error.message}</p>}

        {query.isSuccess && query.data.count === 0 && (
          <p className="text-text-secondary text-sm">No conversations for this customer yet.</p>
        )}

        {query.isSuccess && query.data.count > 0 && (
          <div className="flex flex-col gap-2">
            <ul className="flex flex-col gap-2">
              {query.data.results.slice(0, PREVIEW_COUNT).map((conversation) => (
                <li key={conversation.id} className="flex flex-wrap items-center gap-2 text-sm">
                  <Link
                    href={`/app/inbox/${conversation.id}`}
                    className="text-primary-700 hover:underline focus-visible:underline"
                  >
                    {conversation.subject || "(no subject)"}
                  </Link>
                  <ConversationStatusBadge status={conversation.status} />
                </li>
              ))}
            </ul>
            <Link
              href={`/app/inbox?customer=${customerId}`}
              className="text-primary-700 text-sm hover:underline focus-visible:underline"
            >
              View all {query.data.count} conversation{query.data.count === 1 ? "" : "s"} for this
              customer →
            </Link>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
