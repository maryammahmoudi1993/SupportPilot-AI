"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import {
  WebhookDeliveryStatusBadge,
  webhookEventTypeLabel,
} from "@/features/webhooks/components/webhook-badges";
import { RedriveDeliveryControl } from "@/features/webhooks/components/redrive-delivery-control";
import { useWebhookDeliveryDetailQuery } from "@/features/webhooks/queries";
import { canManageWebhooks, isTerminalDeliveryStatus } from "@/features/webhooks/types";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { EntityNotFound } from "@/components/support/entity-not-found";
import { ListError } from "@/components/support/list-error";
import { Timestamp } from "@/components/support/timestamp";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isValidDeliveryId(deliveryId: string): boolean {
  return UUID_PATTERN.test(deliveryId);
}

function DeliveryNotFound() {
  return (
    <EntityNotFound
      title="Webhook delivery not found"
      description="This webhook delivery doesn't exist, or isn't available in your active workspace."
      backHref="/app/integrations?tab=deliveries"
      backLabel="Back to Deliveries"
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

function WebhookDeliveryDetailContent({
  workspaceId,
  deliveryId,
}: {
  workspaceId: string;
  deliveryId: string;
}) {
  const workspace = useWorkspace();
  const deliveryQuery = useWebhookDeliveryDetailQuery(workspaceId, deliveryId);

  if (deliveryQuery.isPending) {
    return (
      <div className="flex flex-col gap-3" role="status" aria-label="Loading webhook delivery">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
        <span className="sr-only">Loading webhook delivery</span>
      </div>
    );
  }

  if (deliveryQuery.isError) {
    // Same real, stable 404 `not_found` tenant-hiding contract as every
    // other domain — see webhook-endpoint-detail-page.tsx.
    if (deliveryQuery.error.code === "not_found") {
      return <DeliveryNotFound />;
    }
    return (
      <ListError
        message={deliveryQuery.error.message}
        onRetry={() => void deliveryQuery.refetch()}
        isRetrying={deliveryQuery.isFetching}
      />
    );
  }

  const delivery = deliveryQuery.data;
  const isTerminal = isTerminalDeliveryStatus(delivery.status);

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Link
          href="/app/integrations?tab=deliveries"
          className="text-primary-700 text-sm hover:underline"
        >
          ← Back to Deliveries
        </Link>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle>{webhookEventTypeLabel(delivery.event_type)}</CardTitle>
            <WebhookDeliveryStatusBadge status={delivery.status} />
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field
              label="Endpoint"
              value={
                <Link
                  href={`/app/integrations/webhooks/${delivery.endpoint_id}`}
                  className="text-primary-700 hover:underline focus-visible:underline"
                >
                  {delivery.endpoint_name}
                </Link>
              }
            />
            <Field
              label="Processing state"
              value={isTerminal ? "Settled" : "Still in progress"}
            />
            <Field label="Attempts" value={`${delivery.attempt_count} / ${delivery.max_attempts}`} />
            <Field label="Last HTTP status" value={delivery.last_http_status ?? "—"} />
            {/*
              `next_attempt_at` is always a real, non-null timestamp on the
              backend (Delivery.next_attempt_at is NOT NULL) — but it only
              means "when this will next be attempted" while the delivery is
              still non-terminal; a settled delivery's value is stale
              (never re-cleared), so it is deliberately never shown once
              terminal — this chunk never estimates or fabricates a retry
              ETA the backend contract doesn't actually promise (master
              prompt Part D §15).
            */}
            {!isTerminal && (
              <Field label="Next attempt" value={<Timestamp value={delivery.next_attempt_at} />} />
            )}
            <Field label="Created" value={<Timestamp value={delivery.created_at} />} />
            {/*
              "Delivered at"/"Failed at" — deliberately not "Delivered"/
              "Failed" (the status badge's own labels): distinct text avoids
              an ambiguous duplicate-text query in tests and reads more
              clearly as a timestamp field, not a second status indicator.
            */}
            <Field
              label="Delivered at"
              value={delivery.delivered_at ? <Timestamp value={delivery.delivered_at} /> : "—"}
            />
            <Field
              label="Failed at"
              value={delivery.failed_at ? <Timestamp value={delivery.failed_at} /> : "—"}
            />
          </dl>

          {delivery.last_error_code && (
            <dl>
              <dt className="text-text-muted text-xs font-medium uppercase">Last error code</dt>
              <dd className="text-danger-700 mt-1 text-sm break-words whitespace-pre-wrap">
                {delivery.last_error_code}
              </dd>
            </dl>
          )}

          {/*
            At-least-once honesty (master prompt Part D §14): this platform
            never guarantees exactly-once external delivery — a delivered
            status means the endpoint returned 2xx at least once, not that
            it was called exactly once. No request payload or response
            body/headers are ever fetched here: `webhooks/serializers.py
            WebhookDeliverySerializer` never exposes either (verified
            directly against its field list) — there is nothing further to
            render, and this chunk never fabricates one.
          */}
          <p className="text-text-secondary text-xs">
            Webhook delivery is at-least-once, never exactly-once: a status of
            &quot;Delivered&quot; means the endpoint returned a successful response at
            least once, not that it was called only once.
          </p>

          {canManageWebhooks(workspace.activeWorkspace?.role) && (
            <RedriveDeliveryControl workspaceId={workspaceId} delivery={delivery} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export function WebhookDeliveryDetailPage({ deliveryId }: { deliveryId: string }) {
  const workspace = useWorkspace();

  if (!isValidDeliveryId(deliveryId)) {
    return <DeliveryNotFound />;
  }

  if (workspace.status !== "ready" || !workspace.activeWorkspace) {
    return (
      <div className="flex flex-1 items-center justify-center py-16">
        <Spinner label="Loading your workspace" />
      </div>
    );
  }

  return (
    <WebhookDeliveryDetailContent workspaceId={workspace.activeWorkspace.id} deliveryId={deliveryId} />
  );
}
