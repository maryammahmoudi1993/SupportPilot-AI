"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import {
  TicketPriorityBadge,
  TicketStatusBadge,
} from "@/features/tickets/components/ticket-badges";
import { useTicketDetailQuery } from "@/features/tickets/queries";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { CustomerRefLink } from "@/components/support/customer-ref-link";
import { EntityNotFound } from "@/components/support/entity-not-found";
import { ListError } from "@/components/support/list-error";
import { Timestamp } from "@/components/support/timestamp";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isValidTicketId(ticketId: string): boolean {
  return UUID_PATTERN.test(ticketId);
}

function TicketNotFound() {
  return (
    <EntityNotFound
      title="Ticket not found"
      description="This ticket doesn't exist, or isn't available in your active workspace."
      backHref="/app/tickets"
      backLabel="Back to Tickets"
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

function TicketDetailContent({ workspaceId, ticketId }: { workspaceId: string; ticketId: string }) {
  const query = useTicketDetailQuery(workspaceId, ticketId);

  if (query.isPending) {
    return (
      <div className="flex flex-col gap-3" role="status" aria-label="Loading ticket">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
        <span className="sr-only">Loading ticket</span>
      </div>
    );
  }

  if (query.isError) {
    if (query.error.code === "not_found") {
      return <TicketNotFound />;
    }
    return (
      <ListError
        message={query.error.message}
        onRetry={() => void query.refetch()}
        isRetrying={query.isFetching}
      />
    );
  }

  const ticket = query.data;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Link href="/app/tickets" className="text-primary-700 text-sm hover:underline">
          ← Back to Tickets
        </Link>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle>{ticket.subject || "(no subject)"}</CardTitle>
            <TicketStatusBadge status={ticket.status} />
            <TicketPriorityBadge priority={ticket.priority} />
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Customer" value={<CustomerRefLink customerId={ticket.customer_id} />} />
            <Field
              label="Conversation"
              value={
                ticket.conversation_id ? (
                  <Link
                    href={`/app/inbox/${ticket.conversation_id}`}
                    className="text-primary-700 hover:underline focus-visible:underline"
                  >
                    View originating conversation
                  </Link>
                ) : (
                  "— (created directly, not from a conversation)"
                )
              }
            />
            <Field label="Assigned to" value={ticket.assigned_to?.email ?? "Unassigned"} />
            <Field label="Due" value={ticket.due_at ? <Timestamp value={ticket.due_at} /> : "—"} />
            <Field label="Created" value={<Timestamp value={ticket.created_at} />} />
            <Field
              label="Resolved"
              value={ticket.resolved_at ? <Timestamp value={ticket.resolved_at} /> : "—"}
            />
          </dl>
          {ticket.description && (
            <div>
              <dt className="text-text-muted text-xs font-medium uppercase">Description</dt>
              <dd className="text-text-primary mt-1 text-sm break-words whitespace-pre-wrap">
                {ticket.description}
              </dd>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export function TicketDetailPage({ ticketId }: { ticketId: string }) {
  const workspace = useWorkspace();

  if (!isValidTicketId(ticketId)) {
    return <TicketNotFound />;
  }

  if (workspace.status !== "ready" || !workspace.activeWorkspace) {
    return (
      <div className="flex flex-1 items-center justify-center py-16">
        <Spinner label="Loading your workspace" />
      </div>
    );
  }

  return <TicketDetailContent workspaceId={workspace.activeWorkspace.id} ticketId={ticketId} />;
}
