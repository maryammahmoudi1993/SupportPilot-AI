"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { WebhookEndpointStatusBadge } from "@/features/webhooks/components/webhook-badges";
import { useWebhookEndpointDetailQuery } from "@/features/webhooks/queries";
import { subscribedEventTypes } from "@/features/webhooks/types";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { EntityNotFound } from "@/components/support/entity-not-found";
import { ListError } from "@/components/support/list-error";
import { Timestamp } from "@/components/support/timestamp";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isValidEndpointId(endpointId: string): boolean {
  return UUID_PATTERN.test(endpointId);
}

function EndpointNotFound() {
  return (
    <EntityNotFound
      title="Webhook endpoint not found"
      description="This webhook endpoint doesn't exist, or isn't available in your active workspace."
      backHref="/app/integrations?tab=webhooks"
      backLabel="Back to Webhooks"
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

function WebhookEndpointDetailContent({
  workspaceId,
  endpointId,
}: {
  workspaceId: string;
  endpointId: string;
}) {
  const endpointQuery = useWebhookEndpointDetailQuery(workspaceId, endpointId);

  if (endpointQuery.isPending) {
    return (
      <div className="flex flex-col gap-3" role="status" aria-label="Loading webhook endpoint">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
        <span className="sr-only">Loading webhook endpoint</span>
      </div>
    );
  }

  if (endpointQuery.isError) {
    // The backend stably codes every real Http404-raised response as
    // `not_found` — same contract as every other domain (see
    // integration-detail-page.tsx). A foreign workspace's endpoint ID
    // resolves the same way, so this page can never distinguish "doesn't
    // exist" from "belongs to another workspace."
    if (endpointQuery.error.code === "not_found") {
      return <EndpointNotFound />;
    }
    return (
      <ListError
        message={endpointQuery.error.message}
        onRetry={() => void endpointQuery.refetch()}
        isRetrying={endpointQuery.isFetching}
      />
    );
  }

  const endpoint = endpointQuery.data;
  const eventTypes = subscribedEventTypes(endpoint);

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Link
          href="/app/integrations?tab=webhooks"
          className="text-primary-700 text-sm hover:underline"
        >
          ← Back to Webhooks
        </Link>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle>{endpoint.name}</CardTitle>
            <WebhookEndpointStatusBadge status={endpoint.status} />
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {/*
              Master prompt Part B §6: the destination URL is real,
              workspace-member-visible configuration data, shown as plain
              text — never auto-linked (no existing safe-external-link
              policy in this app covers an arbitrary operator-entered
              destination URL), never injected into HTML.
            */}
            <Field label="Destination URL" value={<span className="break-all">{endpoint.url}</span>} />
            {/*
              Signing secret safety (master prompt Part B §7): never the
              raw secret — only the safe, server-derived `secret_configured`
              boolean and `secret_created_at` timestamp.
            */}
            <Field
              label="Signing secret"
              value={endpoint.secret_configured ? "Configured" : "Not configured"}
            />
            <Field
              label="Secret created"
              value={
                endpoint.secret_created_at ? <Timestamp value={endpoint.secret_created_at} /> : "—"
              }
            />
            <Field label="Created" value={<Timestamp value={endpoint.created_at} />} />
            <Field label="Updated" value={<Timestamp value={endpoint.updated_at} />} />
          </dl>

          <div>
            <span className="text-text-muted text-xs font-medium uppercase">
              Subscribed events
            </span>
            {eventTypes.length > 0 ? (
              <ul className="mt-1 flex flex-wrap gap-1.5">
                {eventTypes.map((eventType) => (
                  <li
                    key={eventType}
                    className="bg-surface-2 text-text-secondary rounded-md px-2 py-0.5 text-xs"
                  >
                    {eventType}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-text-secondary mt-1 text-sm">None</p>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export function WebhookEndpointDetailPage({ endpointId }: { endpointId: string }) {
  const workspace = useWorkspace();

  if (!isValidEndpointId(endpointId)) {
    return <EndpointNotFound />;
  }

  if (workspace.status !== "ready" || !workspace.activeWorkspace) {
    return (
      <div className="flex flex-1 items-center justify-center py-16">
        <Spinner label="Loading your workspace" />
      </div>
    );
  }

  return (
    <WebhookEndpointDetailContent workspaceId={workspace.activeWorkspace.id} endpointId={endpointId} />
  );
}
