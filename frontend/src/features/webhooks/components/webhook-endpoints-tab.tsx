"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { WebhookEndpointStatusBadge } from "@/features/webhooks/components/webhook-badges";
import { useWebhookEndpointListQuery } from "@/features/webhooks/queries";
import type { WebhookEndpointListParams } from "@/features/webhooks/types";
import { subscribedEventTypes } from "@/features/webhooks/types";
import { buildWebhookEndpointListQueryString } from "@/features/webhooks/url-params";
import { ListError } from "@/components/support/list-error";
import { Pagination } from "@/components/support/pagination";
import { Timestamp } from "@/components/support/timestamp";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

function EndpointsListSkeleton() {
  return (
    <div className="flex flex-col gap-2" role="status" aria-label="Loading webhook endpoints">
      {Array.from({ length: 4 }).map((_, index) => (
        <Skeleton key={index} className="h-11 w-full" />
      ))}
      <span className="sr-only">Loading webhook endpoints</span>
    </div>
  );
}

export function WebhookEndpointsTab({
  workspaceId,
  pathname,
  params,
}: {
  workspaceId: string;
  pathname: string;
  params: WebhookEndpointListParams;
}) {
  const router = useRouter();
  const query = useWebhookEndpointListQuery(workspaceId, params);

  function pushParams(next: WebhookEndpointListParams) {
    router.replace(`${pathname}${buildWebhookEndpointListQueryString(next)}`, { scroll: false });
  }

  return (
    <div className="flex flex-col gap-6">
      {query.isPending && <EndpointsListSkeleton />}

      {query.isError && (
        <ListError
          message={query.error.message}
          onRetry={() => void query.refetch()}
          isRetrying={query.isFetching}
        />
      )}

      {query.isSuccess && query.data.results.length === 0 && (
        <div className="border-border-subtle rounded-lg border border-dashed py-16 text-center">
          <p className="text-text-primary text-sm font-medium">No webhook endpoints yet</p>
          <p className="text-text-secondary mt-1 text-sm">
            Outbound webhook destinations this workspace has configured will appear here.
          </p>
        </div>
      )}

      {query.isSuccess && query.data.results.length > 0 && (
        <>
          <div className="border-border-subtle overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[720px] text-left text-sm">
              <caption className="sr-only">Webhook endpoints in this workspace</caption>
              <thead className="bg-surface-2 text-text-secondary text-xs font-medium uppercase">
                <tr>
                  <th scope="col" className="px-4 py-2.5">
                    Name
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Status
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Subscribed events
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Signing secret
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Created
                  </th>
                </tr>
              </thead>
              <tbody
                className={cn("divide-border-subtle divide-y", query.isFetching && "opacity-60")}
              >
                {query.data.results.map((endpoint) => (
                  <tr key={endpoint.id} className="hover:bg-surface-2">
                    <td className="px-4 py-2.5 font-medium">
                      <Link
                        href={`/app/integrations/webhooks/${endpoint.id}`}
                        className="text-primary-700 hover:underline focus-visible:underline"
                      >
                        {endpoint.name}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5">
                      <WebhookEndpointStatusBadge status={endpoint.status} />
                    </td>
                    <td className="text-text-secondary px-4 py-2.5">
                      {subscribedEventTypes(endpoint).length}
                    </td>
                    <td className="text-text-secondary px-4 py-2.5">
                      {endpoint.secret_configured ? "Configured" : "Not configured"}
                    </td>
                    <td className="text-text-secondary px-4 py-2.5">
                      <Timestamp value={endpoint.created_at} />
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
            summary={`Page ${params.page} · ${query.data.count} endpoint${query.data.count === 1 ? "" : "s"} total`}
          />
        </>
      )}
    </div>
  );
}
