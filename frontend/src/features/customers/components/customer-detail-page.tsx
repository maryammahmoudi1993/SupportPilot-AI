"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { RelatedConversationsPanel } from "@/features/conversations/components/related-conversations-panel";
import { useCustomerDetailQuery } from "@/features/customers/queries";
import { CustomerStatusBadge } from "@/features/customers/components/customer-status-badge";
import { RelatedTicketsPanel } from "@/features/tickets/components/related-tickets-panel";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { EntityNotFound } from "@/components/support/entity-not-found";
import { ListError } from "@/components/support/list-error";
import { Timestamp } from "@/components/support/timestamp";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";

/** A route param is untrusted input — validate its shape before ever using it in a request. */
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isValidCustomerId(customerId: string): boolean {
  return UUID_PATTERN.test(customerId);
}

function CustomerNotFound() {
  return (
    <EntityNotFound
      title="Customer not found"
      description="This customer doesn't exist, or isn't available in your active workspace."
      backHref="/app/customers"
      backLabel="Back to Customers"
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

function CustomerDetailContent({
  workspaceId,
  customerId,
}: {
  workspaceId: string;
  customerId: string;
}) {
  const query = useCustomerDetailQuery(workspaceId, customerId);

  if (query.isPending) {
    return (
      <div className="flex flex-col gap-3" role="status" aria-label="Loading customer">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
        <span className="sr-only">Loading customer</span>
      </div>
    );
  }

  if (query.isError) {
    if (query.error.code === "not_found") {
      return <CustomerNotFound />;
    }
    return (
      <ListError
        message={query.error.message}
        onRetry={() => void query.refetch()}
        isRetrying={query.isFetching}
      />
    );
  }

  const customer = query.data;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Link href="/app/customers" className="text-primary-700 text-sm hover:underline">
          ← Back to Customers
        </Link>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle>{customer.display_name || "(no name)"}</CardTitle>
            <CustomerStatusBadge isActive={customer.is_active ?? true} />
          </div>
          {customer.company && <CardDescription>{customer.company}</CardDescription>}
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Email" value={customer.email || "—"} />
            <Field label="Phone" value={customer.phone || "—"} />
            <Field label="External ID" value={customer.external_id || "—"} />
            <Field label="Company" value={customer.company || "—"} />
            <Field label="Created" value={<Timestamp value={customer.created_at} />} />
            <Field label="Last updated" value={<Timestamp value={customer.updated_at} />} />
          </dl>
          {customer.notes && (
            <dl className="mt-4">
              <dt className="text-text-muted text-xs font-medium uppercase">Notes</dt>
              <dd className="text-text-primary mt-1 text-sm break-words whitespace-pre-wrap">
                {customer.notes}
              </dd>
            </dl>
          )}
        </CardContent>
      </Card>

      <RelatedConversationsPanel workspaceId={workspaceId} customerId={customerId} />
      <RelatedTicketsPanel workspaceId={workspaceId} customerId={customerId} />
    </div>
  );
}

export function CustomerDetailPage({ customerId }: { customerId: string }) {
  const workspace = useWorkspace();

  if (!isValidCustomerId(customerId)) {
    return <CustomerNotFound />;
  }

  if (workspace.status !== "ready" || !workspace.activeWorkspace) {
    return (
      <div className="flex flex-1 items-center justify-center py-16">
        <Spinner label="Loading your workspace" />
      </div>
    );
  }

  return (
    <CustomerDetailContent workspaceId={workspace.activeWorkspace.id} customerId={customerId} />
  );
}
