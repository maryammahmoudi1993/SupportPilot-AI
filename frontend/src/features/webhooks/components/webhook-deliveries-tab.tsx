"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import {
  WebhookDeliveryStatusBadge,
  webhookEventTypeLabel,
} from "@/features/webhooks/components/webhook-badges";
import { useWebhookDeliveryListQuery } from "@/features/webhooks/queries";
import type { WebhookDeliveryListParams } from "@/features/webhooks/types";
import { toSafeWebhookDelivery } from "@/features/webhooks/types";
import { buildWebhookDeliveryListQueryString } from "@/features/webhooks/url-params";
import { ListError } from "@/components/support/list-error";
import { Pagination } from "@/components/support/pagination";
import { Timestamp } from "@/components/support/timestamp";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

function DeliveriesListSkeleton() {
  return (
    <div className="flex flex-col gap-2" role="status" aria-label="Loading webhook deliveries">
      {Array.from({ length: 4 }).map((_, index) => (
        <Skeleton key={index} className="h-11 w-full" />
      ))}
      <span className="sr-only">Loading webhook deliveries</span>
    </div>
  );
}

export function WebhookDeliveriesTab({
  workspaceId,
  pathname,
  params,
}: {
  workspaceId: string;
  pathname: string;
  params: WebhookDeliveryListParams;
}) {
  const router = useRouter();
  const query = useWebhookDeliveryListQuery(workspaceId, params);

  function pushParams(next: WebhookDeliveryListParams) {
    router.replace(`${pathname}${buildWebhookDeliveryListQueryString(next)}`, { scroll: false });
  }

  return (
    <div className="flex flex-col gap-6">
      {query.isPending && <DeliveriesListSkeleton />}

      {query.isError && (
        <ListError
          message={query.error.message}
          onRetry={() => void query.refetch()}
          isRetrying={query.isFetching}
        />
      )}

      {query.isSuccess && query.data.results.length === 0 && (
        <div className="border-border-subtle rounded-lg border border-dashed py-16 text-center">
          <p className="text-text-primary text-sm font-medium">No webhook deliveries yet</p>
          <p className="text-text-secondary mt-1 text-sm">
            Delivery attempts to this workspace&apos;s webhook endpoints will appear here.
          </p>
        </div>
      )}

      {query.isSuccess && query.data.results.length > 0 && (
        <>
          <div className="border-border-subtle overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[820px] text-left text-sm">
              <caption className="sr-only">Webhook deliveries in this workspace</caption>
              <thead className="bg-surface-2 text-text-secondary text-xs font-medium uppercase">
                <tr>
                  <th scope="col" className="px-4 py-2.5">
                    Event
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Endpoint
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Status
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Attempts
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Last HTTP status
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Created
                  </th>
                </tr>
              </thead>
              <tbody
                className={cn("divide-border-subtle divide-y", query.isFetching && "opacity-60")}
              >
                {query.data.results.map((delivery) => {
                  const safe = toSafeWebhookDelivery(delivery);
                  return (
                    <tr key={safe.delivery_id} className="hover:bg-surface-2">
                      <td className="px-4 py-2.5 font-medium">
                        <Link
                          href={`/app/integrations/deliveries/${safe.delivery_id}`}
                          className="text-primary-700 hover:underline focus-visible:underline"
                        >
                          {webhookEventTypeLabel(safe.event_type)}
                        </Link>
                      </td>
                      <td className="text-text-secondary px-4 py-2.5">{safe.endpoint_name}</td>
                      <td className="px-4 py-2.5">
                        <WebhookDeliveryStatusBadge status={safe.status} />
                      </td>
                      <td className="text-text-secondary px-4 py-2.5">
                        {safe.attempt_count} / {safe.max_attempts}
                      </td>
                      <td className="text-text-secondary px-4 py-2.5">
                        {safe.last_http_status ?? "—"}
                      </td>
                      <td className="text-text-secondary px-4 py-2.5">
                        <Timestamp value={safe.created_at} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <Pagination
            page={params.page}
            hasPrevious={query.data.previous !== null && query.data.previous !== undefined}
            hasNext={query.data.next !== null && query.data.next !== undefined}
            onPrevious={() => pushParams({ ...params, page: Math.max(1, params.page - 1) })}
            onNext={() => pushParams({ ...params, page: params.page + 1 })}
            summary={`Page ${params.page} · ${query.data.count} deliver${query.data.count === 1 ? "y" : "ies"} total`}
          />
        </>
      )}
    </div>
  );
}
