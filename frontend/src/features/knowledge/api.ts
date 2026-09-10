/**
 * Typed API boundary for the knowledge domain — read-only this chunk (master
 * prompt Part E §21): upload/ingestion-trigger/retry/delete/retrieval are
 * real backend endpoints (knowledge/urls.py) but are not called here — see
 * frontend/README.md.
 *
 * Schema gap (Category A, same shape as every other domain — see
 * features/handoffs/api.ts): the generated
 * `api_v1_workspaces_knowledge_documents_list` operation only types
 * `ordering`, `page`, `page_size`, `search`. Empirically (knowledge/tests/
 * test_views.py `test_member_lists_filters_and_gets_document_and_job`) the
 * document list view has NO search filter at all and is filtered by
 * `source_id`/`status` instead — filters the generated schema doesn't type.
 * `ordering` is schema-only/dead for both documents and sources (neither
 * view sets `ordering_fields`; both order deterministically by
 * `-created_at, -id`).
 *
 * The sources list, by contrast, really does support `search` (name/
 * description, case-insensitive) plus a real `is_active` filter the
 * generated schema doesn't type at all.
 */
import { apiClient } from "@/lib/api/client";
import { unwrap, withRequestTimeout } from "@/lib/api/request";
import type {
  KnowledgeDocument,
  KnowledgeDocumentListParams,
  KnowledgeSource,
  KnowledgeSourceListParams,
  PaginatedKnowledgeDocumentList,
  PaginatedKnowledgeSourceList,
} from "@/features/knowledge/types";
import type { paths } from "@/types/api";

type GeneratedDocumentListQuery = NonNullable<
  paths["/api/v1/workspaces/{workspace_id}/knowledge/documents/"]["get"]["parameters"]["query"]
>;

type DocumentListQuery = Omit<GeneratedDocumentListQuery, "ordering" | "search"> & {
  source_id?: string;
  status?: string;
};

function toDocumentListQuery(params: KnowledgeDocumentListParams): DocumentListQuery {
  const query: DocumentListQuery = {};
  if (params.page > 1) {
    query.page = params.page;
  }
  if (params.sourceId !== "all") {
    query.source_id = params.sourceId;
  }
  if (params.status !== "all") {
    query.status = params.status;
  }
  return query;
}

export function fetchKnowledgeDocumentList(
  workspaceId: string,
  params: KnowledgeDocumentListParams,
  signal?: AbortSignal,
): Promise<PaginatedKnowledgeDocumentList> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/knowledge/documents/", {
          params: {
            path: { workspace_id: workspaceId },
            query: toDocumentListQuery(params),
          },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}

export function fetchKnowledgeDocumentDetail(
  workspaceId: string,
  documentId: string,
  signal?: AbortSignal,
): Promise<KnowledgeDocument> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/knowledge/documents/{document_id}/", {
          params: { path: { workspace_id: workspaceId, document_id: documentId } },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}

type GeneratedSourceListQuery = NonNullable<
  paths["/api/v1/workspaces/{workspace_id}/knowledge/sources/"]["get"]["parameters"]["query"]
>;

type SourceListQuery = Omit<GeneratedSourceListQuery, "ordering"> & {
  is_active?: string;
};

function toSourceListQuery(params: KnowledgeSourceListParams): SourceListQuery {
  const query: SourceListQuery = {};
  if (params.page > 1) {
    query.page = params.page;
  }
  if (params.search.trim().length > 0) {
    query.search = params.search.trim();
  }
  if (params.isActive !== "all") {
    query.is_active = params.isActive;
  }
  return query;
}

export function fetchKnowledgeSourceList(
  workspaceId: string,
  params: KnowledgeSourceListParams,
  signal?: AbortSignal,
): Promise<PaginatedKnowledgeSourceList> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/knowledge/sources/", {
          params: {
            path: { workspace_id: workspaceId },
            query: toSourceListQuery(params),
          },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}

/**
 * Fetches every knowledge source for a lightweight "filter by source"
 * control on the Documents list — one bounded list call (max page size),
 * never a per-document lookup (master prompt Part G §33's N+1 prohibition).
 * A workspace with more than 500 sources would need real pagination here;
 * no current workspace does, and this is a filter affordance, not the
 * Sources list of record (see `fetchKnowledgeSourceList` for that).
 */
export function fetchAllKnowledgeSourcesForFilter(
  workspaceId: string,
  signal?: AbortSignal,
): Promise<PaginatedKnowledgeSourceList> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/knowledge/sources/", {
          params: {
            path: { workspace_id: workspaceId },
            query: { page_size: 500 },
          },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}

export function fetchKnowledgeSourceDetail(
  workspaceId: string,
  sourceId: string,
  signal?: AbortSignal,
): Promise<KnowledgeSource> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/knowledge/sources/{source_id}/", {
          params: { path: { workspace_id: workspaceId, source_id: sourceId } },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}
