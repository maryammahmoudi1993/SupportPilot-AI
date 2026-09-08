"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import type { ReactNode } from "react";

import {
  ConversationChannelBadge,
  ConversationStatusBadge,
} from "@/features/conversations/components/conversation-badges";
import { CustomerRefLink } from "@/components/support/customer-ref-link";
import { MessageTimeline } from "@/features/conversations/components/message-timeline";
import { useConversationDetailQuery, useMessageListQuery } from "@/features/conversations/queries";
import { parseMessagePage } from "@/features/conversations/url-params";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { EntityNotFound } from "@/components/support/entity-not-found";
import { ListError } from "@/components/support/list-error";
import { Pagination } from "@/components/support/pagination";
import { Timestamp } from "@/components/support/timestamp";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isValidConversationId(conversationId: string): boolean {
  return UUID_PATTERN.test(conversationId);
}

function ConversationNotFound() {
  return (
    <EntityNotFound
      title="Conversation not found"
      description="This conversation doesn't exist, or isn't available in your active workspace."
      backHref="/app/inbox"
      backLabel="Back to Inbox"
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

function ConversationDetailContent({
  workspaceId,
  conversationId,
}: {
  workspaceId: string;
  conversationId: string;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const messagePage = parseMessagePage(searchParams);

  // Independent, parallel reads — see queries.ts's doc comment on
  // useMessageListQuery: neither request depends on the other's response.
  const conversationQuery = useConversationDetailQuery(workspaceId, conversationId);
  const messagesQuery = useMessageListQuery(workspaceId, conversationId, { page: messagePage });

  if (conversationQuery.isPending) {
    return (
      <div className="flex flex-col gap-3" role="status" aria-label="Loading conversation">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-32 w-full" />
        <span className="sr-only">Loading conversation</span>
      </div>
    );
  }

  if (conversationQuery.isError) {
    if (conversationQuery.error.code === "not_found") {
      return <ConversationNotFound />;
    }
    return (
      <ListError
        message={conversationQuery.error.message}
        onRetry={() => void conversationQuery.refetch()}
        isRetrying={conversationQuery.isFetching}
      />
    );
  }

  const conversation = conversationQuery.data;

  function goToMessagePage(page: number) {
    const next = new URLSearchParams(searchParams.toString());
    if (page > 1) {
      next.set("page", String(page));
    } else {
      next.delete("page");
    }
    const query = next.toString();
    router.replace(`${pathname}${query ? `?${query}` : ""}`, { scroll: false });
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Link href="/app/inbox" className="text-primary-700 text-sm hover:underline">
          ← Back to Inbox
        </Link>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle>{conversation.subject || "(no subject)"}</CardTitle>
            <ConversationStatusBadge status={conversation.status} />
            <ConversationChannelBadge channel={conversation.channel} />
          </div>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field
              label="Customer"
              value={<CustomerRefLink customerId={conversation.customer_id} />}
            />
            <Field label="Assigned to" value={conversation.assigned_to?.email ?? "Unassigned"} />
            <Field label="Started" value={<Timestamp value={conversation.started_at} />} />
            <Field
              label="Last activity"
              value={
                conversation.last_message_at ? (
                  <Timestamp value={conversation.last_message_at} />
                ) : (
                  "—"
                )
              }
            />
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Messages</CardTitle>
        </CardHeader>
        <CardContent>
          {messagesQuery.isPending && (
            <div className="flex flex-col gap-2" role="status" aria-label="Loading messages">
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-16 w-full" />
              <span className="sr-only">Loading messages</span>
            </div>
          )}

          {messagesQuery.isError && (
            <ListError
              message={messagesQuery.error.message}
              onRetry={() => void messagesQuery.refetch()}
              isRetrying={messagesQuery.isFetching}
            />
          )}

          {messagesQuery.isSuccess && messagesQuery.data.results.length === 0 && (
            <p className="text-text-secondary text-sm">No messages in this conversation yet.</p>
          )}

          {messagesQuery.isSuccess && messagesQuery.data.results.length > 0 && (
            <div className="flex flex-col gap-3">
              <MessageTimeline messages={messagesQuery.data.results} />
              {(messagesQuery.data.next || messagesQuery.data.previous) && (
                <Pagination
                  page={messagePage}
                  hasPrevious={
                    messagesQuery.data.previous !== null &&
                    messagesQuery.data.previous !== undefined
                  }
                  hasNext={
                    messagesQuery.data.next !== null && messagesQuery.data.next !== undefined
                  }
                  onPrevious={() => goToMessagePage(Math.max(1, messagePage - 1))}
                  onNext={() => goToMessagePage(messagePage + 1)}
                  summary={`Page ${messagePage} · ${messagesQuery.data.count} message${messagesQuery.data.count === 1 ? "" : "s"} total`}
                />
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function ConversationDetailInner({
  workspaceId,
  conversationId,
}: {
  workspaceId: string;
  conversationId: string;
}) {
  return (
    <Suspense
      fallback={
        <div className="flex flex-1 items-center justify-center py-16">
          <Spinner label="Loading conversation" />
        </div>
      }
    >
      <ConversationDetailContent workspaceId={workspaceId} conversationId={conversationId} />
    </Suspense>
  );
}

export function ConversationDetailPage({ conversationId }: { conversationId: string }) {
  const workspace = useWorkspace();

  if (!isValidConversationId(conversationId)) {
    return <ConversationNotFound />;
  }

  if (workspace.status !== "ready" || !workspace.activeWorkspace) {
    return (
      <div className="flex flex-1 items-center justify-center py-16">
        <Spinner label="Loading your workspace" />
      </div>
    );
  }

  return (
    <ConversationDetailInner
      workspaceId={workspace.activeWorkspace.id}
      conversationId={conversationId}
    />
  );
}
