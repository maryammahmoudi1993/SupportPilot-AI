"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import type { ChangeEvent, ReactNode } from "react";

import {
  KnowledgeDocumentStatusBadge,
  knowledgeSourceTypeLabel,
} from "@/features/knowledge/components/knowledge-badges";
import { KnowledgeSourceCreateForm } from "@/features/knowledge/components/knowledge-source-create-form";
import { KnowledgeUploadForm } from "@/features/knowledge/components/knowledge-upload-form";
import {
  useKnowledgeDocumentListQuery,
  useKnowledgeSourceFilterOptionsQuery,
  useKnowledgeSourceListQuery,
} from "@/features/knowledge/queries";
import type {
  DocumentStatusFilter,
  KnowledgeDocumentListParams,
  KnowledgeSourceListParams,
  SourceActiveFilter,
} from "@/features/knowledge/types";
import { canManageKnowledge } from "@/features/knowledge/types";
import {
  buildKnowledgeDocumentListQueryString,
  buildKnowledgeSourceListQueryString,
  parseKnowledgeDocumentListParams,
  parseKnowledgeSourceListParams,
  parseKnowledgeTab,
  type KnowledgeTab,
} from "@/features/knowledge/url-params";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { ListError } from "@/components/support/list-error";
import { Pagination } from "@/components/support/pagination";
import { Timestamp } from "@/components/support/timestamp";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

const SEARCH_DEBOUNCE_MS = 300;
const DOCUMENT_STATUS_OPTIONS: { value: DocumentStatusFilter; label: string }[] = [
  { value: "all", label: "All statuses" },
  { value: "pending", label: "Pending" },
  { value: "queued", label: "Queued" },
  { value: "processing", label: "Processing" },
  { value: "ready", label: "Ready" },
  { value: "failed", label: "Failed" },
];

const ACTIVE_OPTIONS: { value: SourceActiveFilter; label: string }[] = [
  { value: "all", label: "All sources" },
  { value: "true", label: "Active only" },
  { value: "false", label: "Inactive only" },
];

function TabLink({
  href,
  isActive,
  children,
}: {
  href: string;
  isActive: boolean;
  children: ReactNode;
}) {
  return (
    <Link
      href={href}
      aria-current={isActive ? "page" : undefined}
      className={cn(
        "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
        isActive
          ? "bg-primary-500 text-text-inverse"
          : "text-text-secondary hover:bg-surface-2 hover:text-text-primary",
      )}
    >
      {children}
    </Link>
  );
}

function DocumentsTab({
  workspaceId,
  pathname,
  params,
  canManage,
}: {
  workspaceId: string;
  pathname: string;
  params: KnowledgeDocumentListParams;
  canManage: boolean;
}) {
  const router = useRouter();
  const query = useKnowledgeDocumentListQuery(workspaceId, params);
  const sourceOptions = useKnowledgeSourceFilterOptionsQuery(workspaceId);
  const [isUploadOpen, setIsUploadOpen] = useState(false);

  function pushParams(next: KnowledgeDocumentListParams) {
    router.replace(`${pathname}${buildKnowledgeDocumentListQueryString(next)}`, { scroll: false });
  }

  function handleSourceChange(event: ChangeEvent<HTMLSelectElement>) {
    pushParams({ ...params, sourceId: event.target.value as string | "all", page: 1 });
  }

  function handleStatusChange(event: ChangeEvent<HTMLSelectElement>) {
    pushParams({ ...params, status: event.target.value as DocumentStatusFilter, page: 1 });
  }

  const hasFilters = params.sourceId !== "all" || params.status !== "all";

  return (
    <div className="flex flex-col gap-6">
      {canManage && (
        <div className="flex flex-col gap-3">
          <div>
            <Button size="sm" onClick={() => setIsUploadOpen((open) => !open)}>
              {isUploadOpen ? "Cancel upload" : "Upload document"}
            </Button>
          </div>
          {isUploadOpen && (
            <KnowledgeUploadForm
              workspaceId={workspaceId}
              onCancel={() => setIsUploadOpen(false)}
            />
          )}
        </div>
      )}

      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
        <div className="w-full sm:w-64">
          <Label htmlFor="knowledge-source-filter">Source</Label>
          <select
            id="knowledge-source-filter"
            value={params.sourceId}
            onChange={handleSourceChange}
            className="bg-surface-0 text-text-primary border-border-default focus-visible:outline-primary-500 h-9 w-full rounded-md border px-3 text-sm outline-none"
          >
            <option value="all">All sources</option>
            {sourceOptions.isSuccess &&
              sourceOptions.data.results.map((source) => (
                <option key={source.id} value={source.id}>
                  {source.name}
                </option>
              ))}
          </select>
        </div>
        <div className="w-full sm:w-56">
          <Label htmlFor="knowledge-status-filter">Status</Label>
          <select
            id="knowledge-status-filter"
            value={params.status}
            onChange={handleStatusChange}
            className="bg-surface-0 text-text-primary border-border-default focus-visible:outline-primary-500 h-9 w-full rounded-md border px-3 text-sm outline-none"
          >
            {DOCUMENT_STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {query.isPending && <KnowledgeListSkeleton label="Loading knowledge documents" />}

      {query.isError && (
        <ListError
          message={query.error.message}
          onRetry={() => void query.refetch()}
          isRetrying={query.isFetching}
        />
      )}

      {query.isSuccess && query.data.results.length === 0 && (
        <div className="border-border-subtle rounded-lg border border-dashed py-16 text-center">
          <p className="text-text-primary text-sm font-medium">
            {hasFilters ? "No documents match your filters" : "No knowledge documents yet"}
          </p>
          <p className="text-text-secondary mt-1 text-sm">
            {hasFilters
              ? "Try a different source or status."
              : "Documents ingested into this workspace's knowledge base will appear here."}
          </p>
        </div>
      )}

      {query.isSuccess && query.data.results.length > 0 && (
        <>
          <div className="border-border-subtle overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[720px] text-left text-sm">
              <caption className="sr-only">Knowledge documents in this workspace</caption>
              <thead className="bg-surface-2 text-text-secondary text-xs font-medium uppercase">
                <tr>
                  <th scope="col" className="px-4 py-2.5">
                    Title
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Source
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Status
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Chunks
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Created
                  </th>
                </tr>
              </thead>
              <tbody
                className={cn("divide-border-subtle divide-y", query.isFetching && "opacity-60")}
              >
                {query.data.results.map((document) => (
                  <tr key={document.id} className="hover:bg-surface-2">
                    <td className="px-4 py-2.5 font-medium">
                      <Link
                        href={`/app/knowledge/${document.id}`}
                        className="text-primary-700 hover:underline focus-visible:underline"
                      >
                        {document.title}
                      </Link>
                    </td>
                    <td className="text-text-secondary px-4 py-2.5">{document.source_name}</td>
                    <td className="px-4 py-2.5">
                      <KnowledgeDocumentStatusBadge status={document.status} />
                    </td>
                    <td className="text-text-secondary px-4 py-2.5">{document.chunk_count}</td>
                    <td className="text-text-secondary px-4 py-2.5">
                      <Timestamp value={document.created_at} />
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
            summary={`Page ${params.page} · ${query.data.count} document${query.data.count === 1 ? "" : "s"} total`}
          />
        </>
      )}
    </div>
  );
}

function SourcesTab({
  workspaceId,
  pathname,
  params,
  canManage,
}: {
  workspaceId: string;
  pathname: string;
  params: KnowledgeSourceListParams;
  canManage: boolean;
}) {
  const router = useRouter();
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [searchInput, setSearchInput] = useState(params.search);
  // Mirrors `params.search` so external URL changes (browser back/forward, a
  // pasted link) can reset the field — same pattern as
  // features/customers/components/customers-list-page.tsx.
  const [syncedSearch, setSyncedSearch] = useState(params.search);
  if (params.search !== syncedSearch) {
    setSyncedSearch(params.search);
    setSearchInput(params.search);
  }

  function pushParams(next: KnowledgeSourceListParams) {
    router.replace(`${pathname}${buildKnowledgeSourceListQueryString(next)}`, { scroll: false });
  }

  // Debounced search-as-you-type: `search` is a plain `icontains` query
  // param (knowledge/selectors.py `source_list_for_workspace`), so type-ahead
  // is appropriate, but every keystroke hitting the network would not be.
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

  const query = useKnowledgeSourceListQuery(workspaceId, params);

  function handleActiveChange(event: ChangeEvent<HTMLSelectElement>) {
    pushParams({ ...params, isActive: event.target.value as SourceActiveFilter, page: 1 });
  }

  const hasFilters = params.search.trim().length > 0 || params.isActive !== "all";

  return (
    <div className="flex flex-col gap-6">
      {canManage && (
        <div className="flex flex-col gap-3">
          <div>
            <Button size="sm" onClick={() => setIsCreateOpen((open) => !open)}>
              {isCreateOpen ? "Cancel" : "New source"}
            </Button>
          </div>
          {isCreateOpen && (
            <KnowledgeSourceCreateForm
              workspaceId={workspaceId}
              onCreated={() => setIsCreateOpen(false)}
              onCancel={() => setIsCreateOpen(false)}
            />
          )}
        </div>
      )}

      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
        <div className="w-full sm:w-72">
          <Label htmlFor="knowledge-source-search">Search</Label>
          <Input
            id="knowledge-source-search"
            type="search"
            placeholder="Search by name or description"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
          />
        </div>
        <div className="w-full sm:w-56">
          <Label htmlFor="knowledge-source-active-filter">Status</Label>
          <select
            id="knowledge-source-active-filter"
            value={params.isActive}
            onChange={handleActiveChange}
            className="bg-surface-0 text-text-primary border-border-default focus-visible:outline-primary-500 h-9 w-full rounded-md border px-3 text-sm outline-none"
          >
            {ACTIVE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {query.isPending && <KnowledgeListSkeleton label="Loading knowledge sources" />}

      {query.isError && (
        <ListError
          message={query.error.message}
          onRetry={() => void query.refetch()}
          isRetrying={query.isFetching}
        />
      )}

      {query.isSuccess && query.data.results.length === 0 && (
        <div className="border-border-subtle rounded-lg border border-dashed py-16 text-center">
          <p className="text-text-primary text-sm font-medium">
            {hasFilters ? "No sources match your filters" : "No knowledge sources yet"}
          </p>
          <p className="text-text-secondary mt-1 text-sm">
            {hasFilters
              ? "Try a different search term or status."
              : "Sources documents are grouped under will appear here."}
          </p>
        </div>
      )}

      {query.isSuccess && query.data.results.length > 0 && (
        <>
          <div className="border-border-subtle overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[640px] text-left text-sm">
              <caption className="sr-only">Knowledge sources in this workspace</caption>
              <thead className="bg-surface-2 text-text-secondary text-xs font-medium uppercase">
                <tr>
                  <th scope="col" className="px-4 py-2.5">
                    Name
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Type
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Active
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Created
                  </th>
                </tr>
              </thead>
              <tbody
                className={cn("divide-border-subtle divide-y", query.isFetching && "opacity-60")}
              >
                {query.data.results.map((source) => (
                  <tr key={source.id}>
                    <td className="px-4 py-2.5 font-medium">
                      <div className="text-text-primary">{source.name}</div>
                      {source.description && (
                        <div className="text-text-secondary text-xs">{source.description}</div>
                      )}
                    </td>
                    <td className="text-text-secondary px-4 py-2.5">
                      {knowledgeSourceTypeLabel(source.source_type)}
                    </td>
                    <td className="text-text-secondary px-4 py-2.5">
                      {source.is_active ? "Active" : "Inactive"}
                    </td>
                    <td className="text-text-secondary px-4 py-2.5">
                      <Timestamp value={source.created_at} />
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
            summary={`Page ${params.page} · ${query.data.count} source${query.data.count === 1 ? "" : "s"} total`}
          />
        </>
      )}
    </div>
  );
}

function KnowledgeListSkeleton({ label }: { label: string }) {
  return (
    <div className="flex flex-col gap-2" role="status" aria-label={label}>
      {Array.from({ length: 6 }).map((_, index) => (
        <Skeleton key={index} className="h-11 w-full" />
      ))}
      <span className="sr-only">{label}</span>
    </div>
  );
}

function KnowledgeListContent() {
  const workspace = useWorkspace();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const workspaceId = workspace.activeWorkspace?.id ?? null;
  const canManage = canManageKnowledge(workspace.activeWorkspace?.role);
  const tab: KnowledgeTab = parseKnowledgeTab(searchParams);
  const documentParams = parseKnowledgeDocumentListParams(searchParams);
  const sourceParams = parseKnowledgeSourceListParams(searchParams);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-text-primary text-xl font-semibold">Knowledge</h1>
        <p className="text-text-secondary text-sm">
          Real documents and sources feeding this workspace&apos;s retrieval pipeline.
        </p>
      </div>

      <div role="tablist" aria-label="Knowledge views" className="flex gap-2">
        <TabLink href={pathname} isActive={tab === "documents"}>
          Documents
        </TabLink>
        <TabLink href={`${pathname}?tab=sources`} isActive={tab === "sources"}>
          Sources
        </TabLink>
      </div>

      {workspaceId === null ? (
        <KnowledgeListSkeleton label="Loading knowledge" />
      ) : tab === "documents" ? (
        <DocumentsTab
          workspaceId={workspaceId}
          pathname={pathname}
          params={documentParams}
          canManage={canManage}
        />
      ) : (
        <SourcesTab
          workspaceId={workspaceId}
          pathname={pathname}
          params={sourceParams}
          canManage={canManage}
        />
      )}
    </div>
  );
}

export function KnowledgeListPage() {
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
          <Spinner label="Loading knowledge" />
        </div>
      }
    >
      <KnowledgeListContent />
    </Suspense>
  );
}
