"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import type { ChangeEvent } from "react";

import { CustomerStatusBadge } from "@/features/customers/components/customer-status-badge";
import { useCustomerListQuery } from "@/features/customers/queries";
import type { CustomerListParams, CustomerStatusFilter } from "@/features/customers/types";
import { buildCustomerListQueryString, parseCustomerListParams } from "@/features/customers/url-params";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { ListError } from "@/components/support/list-error";
import { Pagination } from "@/components/support/pagination";
import { Timestamp } from "@/components/support/timestamp";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

const SEARCH_DEBOUNCE_MS = 300;
const STATUS_OPTIONS: { value: CustomerStatusFilter; label: string }[] = [
  { value: "all", label: "All customers" },
  { value: "active", label: "Active only" },
  { value: "inactive", label: "Inactive only" },
];

function CustomersListContent() {
  const workspace = useWorkspace();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const params = parseCustomerListParams(searchParams);
  const [searchInput, setSearchInput] = useState(params.search);
  // Mirrors `params.search` so external URL changes (browser back/forward, a
  // pasted link) can reset the field. Adjusted during render, not in an
  // effect — the recommended React pattern for "state derived from a prop
  // that can also be locally edited" (see https://react.dev/learn/you-
  // might-not-need-an-effect#adjusting-some-state-when-a-prop-changes);
  // an effect here would cause an extra render pass for no benefit.
  const [syncedSearch, setSyncedSearch] = useState(params.search);
  if (params.search !== syncedSearch) {
    setSyncedSearch(params.search);
    setSearchInput(params.search);
  }

  function pushParams(next: CustomerListParams) {
    router.replace(`${pathname}${buildCustomerListQueryString(next)}`, { scroll: false });
  }

  // Debounced search-as-you-type: the backend has no explicit-submit
  // contract for `search` (it's a plain `icontains` query param — see
  // customers/selectors.py), so type-ahead is appropriate, but every
  // keystroke hitting the network would not be responsible use of it.
  useEffect(() => {
    const trimmed = searchInput.trim();
    if (trimmed === params.search) {
      return;
    }
    const timer = setTimeout(() => {
      pushParams({ ...params, search: trimmed, page: 1 });
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput]);

  const workspaceId = workspace.activeWorkspace?.id ?? null;
  const query = useCustomerListQuery(workspaceId, params);

  function handleStatusChange(event: ChangeEvent<HTMLSelectElement>) {
    pushParams({ ...params, status: event.target.value as CustomerStatusFilter, page: 1 });
  }

  const hasFilters = params.search.trim().length > 0 || params.status !== "all";

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-text-primary text-xl font-semibold">Customers</h1>
        <p className="text-text-secondary text-sm">
          Browse the customers this workspace supports.
        </p>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="max-w-sm flex-1">
          <Label htmlFor="customer-search">Search customers</Label>
          <Input
            id="customer-search"
            type="search"
            placeholder="Name, email, phone, company..."
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
          />
        </div>
        <div className="w-full sm:w-56">
          <Label htmlFor="customer-status-filter">Status</Label>
          <select
            id="customer-status-filter"
            value={params.status}
            onChange={handleStatusChange}
            className="bg-surface-0 text-text-primary border-border-default focus-visible:outline-primary-500 h-9 w-full rounded-md border px-3 text-sm outline-none"
          >
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {query.isPending && <CustomersListSkeleton />}

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
            {hasFilters ? "No customers match your filters" : "No customers yet"}
          </p>
          <p className="text-text-secondary mt-1 text-sm">
            {hasFilters
              ? "Try a different search term or status."
              : "Customers this workspace supports will appear here."}
          </p>
        </div>
      )}

      {query.isSuccess && query.data.results.length > 0 && (
        <>
          <div className="border-border-subtle overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[640px] text-left text-sm">
              <caption className="sr-only">Customers in this workspace</caption>
              <thead className="bg-surface-2 text-text-secondary text-xs font-medium uppercase">
                <tr>
                  <th scope="col" className="px-4 py-2.5">
                    Name
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Email
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Company
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Status
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Created
                  </th>
                </tr>
              </thead>
              <tbody className={cn("divide-y divide-border-subtle", query.isFetching && "opacity-60")}>
                {query.data.results.map((customer) => (
                  <tr key={customer.id} className="hover:bg-surface-2">
                    <td className="px-4 py-2.5 font-medium">
                      <Link
                        href={`/app/customers/${customer.id}`}
                        className="text-primary-700 hover:underline focus-visible:underline"
                      >
                        {customer.display_name || "(no name)"}
                      </Link>
                    </td>
                    <td className="text-text-secondary px-4 py-2.5">{customer.email || "—"}</td>
                    <td className="text-text-secondary px-4 py-2.5">{customer.company || "—"}</td>
                    <td className="px-4 py-2.5">
                      <CustomerStatusBadge isActive={customer.is_active ?? true} />
                    </td>
                    <td className="text-text-secondary px-4 py-2.5">
                      <Timestamp value={customer.created_at} />
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
            summary={`Page ${params.page} · ${query.data.count} customer${query.data.count === 1 ? "" : "s"} total`}
          />
        </>
      )}
    </div>
  );
}

function CustomersListSkeleton() {
  return (
    <div className="flex flex-col gap-2" role="status" aria-label="Loading customers">
      {Array.from({ length: 6 }).map((_, index) => (
        <Skeleton key={index} className="h-11 w-full" />
      ))}
      <span className="sr-only">Loading customers</span>
    </div>
  );
}

/**
 * Top-level route component. `useSearchParams` requires a `<Suspense>`
 * boundary in the app router (see login/page.tsx for the same pattern
 * already established in Phase 18).
 */
export function CustomersListPage() {
  const workspace = useWorkspace();

  // Distinct "no accessible workspace" state — `AppShell`'s `WorkspaceGate`
  // already keeps this page from rendering at all for "loading"/"idle"/
  // "error"/"empty", but `activeWorkspace` can still legitimately be null
  // for a beat while `WorkspaceProvider` repairs the selection (see
  // features/workspace/workspace-provider.tsx) — render nothing privileged
  // rather than querying with a stale/empty workspace ID.
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
          <Spinner label="Loading customers" />
        </div>
      }
    >
      <CustomersListContent />
    </Suspense>
  );
}
