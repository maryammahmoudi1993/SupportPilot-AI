"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import {
  IntegrationConnectionStatusBadge,
  IntegrationEnvironmentBadge,
  integrationProviderLabel,
} from "@/features/integrations/components/integration-badges";
import { useIntegrationConnectionListQuery } from "@/features/integrations/queries";
import type { IntegrationConnectionListParams } from "@/features/integrations/types";
import {
  buildIntegrationConnectionListQueryString,
  parseIntegrationConnectionListParams,
} from "@/features/integrations/url-params";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { ListError } from "@/components/support/list-error";
import { Pagination } from "@/components/support/pagination";
import { Timestamp } from "@/components/support/timestamp";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

function IntegrationsListSkeleton() {
  return (
    <div className="flex flex-col gap-2" role="status" aria-label="Loading integration connections">
      {Array.from({ length: 4 }).map((_, index) => (
        <Skeleton key={index} className="h-11 w-full" />
      ))}
      <span className="sr-only">Loading integration connections</span>
    </div>
  );
}

function IntegrationsListContent({
  workspaceId,
  pathname,
  params,
}: {
  workspaceId: string;
  pathname: string;
  params: IntegrationConnectionListParams;
}) {
  const router = useRouter();
  const query = useIntegrationConnectionListQuery(workspaceId, params);

  function pushParams(next: IntegrationConnectionListParams) {
    router.replace(`${pathname}${buildIntegrationConnectionListQueryString(next)}`, {
      scroll: false,
    });
  }

  return (
    <div className="flex flex-col gap-6">
      {query.isPending && <IntegrationsListSkeleton />}

      {query.isError && (
        <ListError
          message={query.error.message}
          onRetry={() => void query.refetch()}
          isRetrying={query.isFetching}
        />
      )}

      {query.isSuccess && query.data.results.length === 0 && (
        <div className="border-border-subtle rounded-lg border border-dashed py-16 text-center">
          <p className="text-text-primary text-sm font-medium">No integration connections yet</p>
          <p className="text-text-secondary mt-1 text-sm">
            Connections this workspace has configured with external providers will appear here.
          </p>
        </div>
      )}

      {query.isSuccess && query.data.results.length > 0 && (
        <>
          <div className="border-border-subtle overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[720px] text-left text-sm">
              <caption className="sr-only">Integration connections in this workspace</caption>
              <thead className="bg-surface-2 text-text-secondary text-xs font-medium uppercase">
                <tr>
                  <th scope="col" className="px-4 py-2.5">
                    Provider
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Status
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Environment
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Credentials
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Last checked
                  </th>
                </tr>
              </thead>
              <tbody
                className={cn("divide-border-subtle divide-y", query.isFetching && "opacity-60")}
              >
                {query.data.results.map((connection) => (
                  <tr key={connection.id} className="hover:bg-surface-2">
                    <td className="px-4 py-2.5 font-medium">
                      <Link
                        href={`/app/integrations/${connection.id}`}
                        className="text-primary-700 hover:underline focus-visible:underline"
                      >
                        {connection.display_name || integrationProviderLabel(connection.provider)}
                      </Link>
                      {connection.display_name && (
                        <div className="text-text-secondary text-xs">
                          {integrationProviderLabel(connection.provider)}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      <IntegrationConnectionStatusBadge status={connection.status} />
                    </td>
                    <td className="px-4 py-2.5">
                      <IntegrationEnvironmentBadge environment={connection.environment} />
                    </td>
                    <td className="text-text-secondary px-4 py-2.5">
                      {connection.credentials_configured ? "Configured" : "Not configured"}
                    </td>
                    <td className="text-text-secondary px-4 py-2.5">
                      {connection.last_checked_at ? (
                        <Timestamp value={connection.last_checked_at} />
                      ) : (
                        "—"
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
            summary={`Page ${params.page} · ${query.data.count} connection${query.data.count === 1 ? "" : "s"} total`}
          />
        </>
      )}
    </div>
  );
}

function IntegrationsListInner() {
  const workspace = useWorkspace();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const workspaceId = workspace.activeWorkspace?.id ?? null;
  const params = parseIntegrationConnectionListParams(searchParams);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-text-primary text-xl font-semibold">Integrations</h1>
        <p className="text-text-secondary text-sm">
          Real external-provider connections configured for this workspace.
        </p>
      </div>

      {workspaceId === null ? (
        <IntegrationsListSkeleton />
      ) : (
        <IntegrationsListContent workspaceId={workspaceId} pathname={pathname} params={params} />
      )}
    </div>
  );
}

export function IntegrationsListPage() {
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
          <Spinner label="Loading integrations" />
        </div>
      }
    >
      <IntegrationsListInner />
    </Suspense>
  );
}
