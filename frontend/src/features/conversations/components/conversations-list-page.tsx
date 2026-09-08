"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import type { ChangeEvent } from "react";

import {
  ConversationChannelBadge,
  ConversationStatusBadge,
} from "@/features/conversations/components/conversation-badges";
import { CustomerRefLink } from "@/features/conversations/components/customer-ref-link";
import { useConversationListQuery } from "@/features/conversations/queries";
import type {
  ConversationAssignmentFilter,
  ConversationChannelFilter,
  ConversationListParams,
  ConversationStatusFilter,
} from "@/features/conversations/types";
import {
  buildConversationListQueryString,
  parseConversationListParams,
} from "@/features/conversations/url-params";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { ListError } from "@/components/support/list-error";
import { Pagination } from "@/components/support/pagination";
import { Timestamp } from "@/components/support/timestamp";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

const STATUS_OPTIONS: { value: ConversationStatusFilter; label: string }[] = [
  { value: "all", label: "All statuses" },
  { value: "open", label: "Open" },
  { value: "pending", label: "Pending" },
  { value: "closed", label: "Closed" },
];

const CHANNEL_OPTIONS: { value: ConversationChannelFilter; label: string }[] = [
  { value: "all", label: "All channels" },
  { value: "web", label: "Web" },
  { value: "chat", label: "Chat" },
  { value: "email", label: "Email" },
  { value: "sms", label: "SMS" },
  { value: "api", label: "API" },
];

const ASSIGNMENT_OPTIONS: { value: ConversationAssignmentFilter; label: string }[] = [
  { value: "all", label: "All conversations" },
  { value: "unassigned", label: "Unassigned only" },
];

function ConversationsListContent() {
  const workspace = useWorkspace();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const params = parseConversationListParams(searchParams);
  const workspaceId = workspace.activeWorkspace?.id ?? null;
  const query = useConversationListQuery(workspaceId, params);

  function pushParams(next: ConversationListParams) {
    router.replace(`${pathname}${buildConversationListQueryString(next)}`, { scroll: false });
  }

  function handleSelectChange(field: "status" | "channel" | "assigned") {
    return (event: ChangeEvent<HTMLSelectElement>) => {
      const value = event.target.value;
      if (field === "status") {
        pushParams({ ...params, status: value as ConversationStatusFilter, page: 1 });
      } else if (field === "channel") {
        pushParams({ ...params, channel: value as ConversationChannelFilter, page: 1 });
      } else {
        pushParams({ ...params, assignment: value as ConversationAssignmentFilter, page: 1 });
      }
    };
  }

  const hasFilters =
    params.status !== "all" || params.channel !== "all" || params.assignment !== "all";

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-text-primary text-xl font-semibold">Inbox</h1>
        <p className="text-text-secondary text-sm">Conversations this workspace is handling.</p>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
        <div className="w-full sm:w-48">
          <Label htmlFor="conversation-status-filter">Status</Label>
          <select
            id="conversation-status-filter"
            value={params.status}
            onChange={handleSelectChange("status")}
            className="bg-surface-0 text-text-primary border-border-default focus-visible:outline-primary-500 h-9 w-full rounded-md border px-3 text-sm outline-none"
          >
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div className="w-full sm:w-48">
          <Label htmlFor="conversation-channel-filter">Channel</Label>
          <select
            id="conversation-channel-filter"
            value={params.channel}
            onChange={handleSelectChange("channel")}
            className="bg-surface-0 text-text-primary border-border-default focus-visible:outline-primary-500 h-9 w-full rounded-md border px-3 text-sm outline-none"
          >
            {CHANNEL_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div className="w-full sm:w-48">
          <Label htmlFor="conversation-assignment-filter">Assignment</Label>
          <select
            id="conversation-assignment-filter"
            value={params.assignment}
            onChange={handleSelectChange("assigned")}
            className="bg-surface-0 text-text-primary border-border-default focus-visible:outline-primary-500 h-9 w-full rounded-md border px-3 text-sm outline-none"
          >
            {ASSIGNMENT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {query.isPending && <ConversationsListSkeleton />}

      {query.isError && (
        <ListError
          message={query.error.message}
          onRetry={() => void query.refetch()}
          isRetrying={query.isFetching}
        />
      )}

      {query.isSuccess && query.data.results.length === 0 && (
        <div className="rounded-lg border border-dashed py-16 text-center border-border-subtle">
          <p className="text-text-primary text-sm font-medium">
            {hasFilters ? "No conversations match your filters" : "No conversations yet"}
          </p>
          <p className="text-text-secondary mt-1 text-sm">
            {hasFilters
              ? "Try a different status, channel, or assignment filter."
              : "Conversations this workspace handles will appear here."}
          </p>
        </div>
      )}

      {query.isSuccess && query.data.results.length > 0 && (
        <>
          <div className="border-border-subtle overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[720px] text-left text-sm">
              <caption className="sr-only">Conversations in this workspace</caption>
              <thead className="bg-surface-2 text-text-secondary text-xs font-medium uppercase">
                <tr>
                  <th scope="col" className="px-4 py-2.5">
                    Subject
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Customer
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Channel
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Status
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Assigned
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Last activity
                  </th>
                </tr>
              </thead>
              <tbody className={cn("divide-y divide-border-subtle", query.isFetching && "opacity-60")}>
                {query.data.results.map((conversation) => (
                  <tr key={conversation.id} className="hover:bg-surface-2">
                    <td className="px-4 py-2.5 font-medium">
                      <Link
                        href={`/app/inbox/${conversation.id}`}
                        className="text-primary-700 hover:underline focus-visible:underline"
                      >
                        {conversation.subject || "(no subject)"}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5">
                      <CustomerRefLink customerId={conversation.customer_id} />
                    </td>
                    <td className="px-4 py-2.5">
                      <ConversationChannelBadge channel={conversation.channel} />
                    </td>
                    <td className="px-4 py-2.5">
                      <ConversationStatusBadge status={conversation.status} />
                    </td>
                    <td className="text-text-secondary px-4 py-2.5">
                      {conversation.assigned_to?.email ?? "Unassigned"}
                    </td>
                    <td className="text-text-secondary px-4 py-2.5">
                      {conversation.last_message_at ? (
                        <Timestamp value={conversation.last_message_at} />
                      ) : (
                        <Timestamp value={conversation.started_at} />
                      )}
                    </td>
                  </tr>
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
            summary={`Page ${params.page} · ${query.data.count} conversation${query.data.count === 1 ? "" : "s"} total`}
          />
        </>
      )}
    </div>
  );
}

function ConversationsListSkeleton() {
  return (
    <div className="flex flex-col gap-2" role="status" aria-label="Loading conversations">
      {Array.from({ length: 6 }).map((_, index) => (
        <Skeleton key={index} className="h-11 w-full" />
      ))}
      <span className="sr-only">Loading conversations</span>
    </div>
  );
}

export function ConversationsListPage() {
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
          <Spinner label="Loading conversations" />
        </div>
      }
    >
      <ConversationsListContent />
    </Suspense>
  );
}
