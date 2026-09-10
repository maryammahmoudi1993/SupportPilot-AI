/**
 * Typed API boundary for the knowledge domain.
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
 *
 * Schema gap (Chunk 2, upload): the generated
 * `api_v1_workspaces_knowledge_documents_create` operation types its
 * `multipart/form-data` request body as `KnowledgeDocumentUpload`, whose
 * `file` field is typed `string` (openapi-typescript has no way to express
 * "binary file" for a multipart body — a known, general limitation, not
 * specific to this endpoint). The real backend
 * (`KnowledgeDocumentUploadSerializer`) expects an actual `File`/`Blob`.
 * `uploadKnowledgeDocument` below builds a real `FormData` (verified against
 * `knowledge/tests/test_views.py`'s exact field names: `source_id`, `title`,
 * `file`) and casts it to the generated body type at the one call site that
 * needs it — an explicit, narrow, documented cast, never `any`/`ts-ignore`.
 */
import { apiClient } from "@/lib/api/client";
import { requestWithTimeout, unwrap, withRequestTimeout } from "@/lib/api/request";
import type {
  CreateKnowledgeSourceInput,
  KnowledgeDocument,
  KnowledgeDocumentListParams,
  KnowledgeIngestionJob,
  KnowledgeSearchRequestInput,
  KnowledgeSearchResponse,
  KnowledgeSource,
  KnowledgeSourceListParams,
  PaginatedKnowledgeDocumentList,
  PaginatedKnowledgeSourceList,
  UploadKnowledgeDocumentInput,
} from "@/features/knowledge/types";
import type { components, paths } from "@/types/api";

/** Upload can carry up to `KNOWLEDGE_MAX_UPLOAD_BYTES` (10 MiB default) — longer than the app's default 15s request timeout on a slow connection. */
const UPLOAD_TIMEOUT_MS = 60_000;

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

/**
 * Minimal source creation (master prompt Part I §34) — only the fields this
 * chunk's upload flow actually needs; `is_active`/`metadata` are left to
 * their real backend defaults (`true`/`{}`) rather than exposed here, since
 * nothing in this chunk's UI needs to set them. `source_type: "upload"` is
 * sent explicitly even though the backend itself defaults to the same value
 * (`KnowledgeSourceType.UPLOAD`) — the generated schema's `source_type`
 * field is (incorrectly) required, not optional, despite the backend
 * serializer's real `required=False, default=upload` — see the module doc
 * comment's Chunk 2 schema-gap list.
 *
 * Schema gap (Chunk 2, response type): the generated
 * `api_v1_workspaces_knowledge_sources_create` operation types its 201
 * response as `KnowledgeSourceWrite` (the *request* shape) rather than the
 * real response body — verified directly against `knowledge/views.py`
 * `KnowledgeSourceListCreateView.create`, which returns
 * `KnowledgeSourceSerializer(source).data` (the full object, including
 * `id`/`created_at`/`updated_at`). An explicit, narrow cast at this one call
 * site corrects it — never `any`/`ts-ignore`.
 */
export function createKnowledgeSource(
  workspaceId: string,
  input: CreateKnowledgeSourceInput,
): Promise<KnowledgeSource> {
  return requestWithTimeout((signal) =>
    apiClient.POST("/api/v1/workspaces/{workspace_id}/knowledge/sources/", {
      params: { path: { workspace_id: workspaceId } },
      body: { name: input.name, description: input.description, source_type: "upload" },
      signal,
    }),
  ) as unknown as Promise<KnowledgeSource>;
}

/**
 * Real multipart field names only (knowledge/serializers.py
 * `KnowledgeDocumentUploadSerializer`, verified against
 * `test_manager_uploads_multipart_and_internal_fields_are_ignored`): the
 * backend derives every other document field itself (status, chunk_count,
 * workspace, ...) — it silently ignores any other field a client sends
 * (that same test posts a spoofed `status`/`chunk_count`/`workspace` and
 * asserts they're discarded), so nothing else is ever built into this
 * FormData. No idempotency key/dedupe token exists on this endpoint (see
 * mutations.ts's ambiguous-network-failure handling for why this matters).
 *
 * Schema gap (Chunk 2, response type): the generated
 * `api_v1_workspaces_knowledge_documents_create` operation types its 201
 * response as `KnowledgeDocumentUpload` (the *request* shape) rather than
 * the real `{document, ingestion_job}` body — verified directly against
 * `knowledge/views.py` `KnowledgeDocumentListCreateView.create` and
 * `KnowledgeDocumentUploadResponseSerializer`. Corrected with the same
 * explicit, narrow cast pattern as `createKnowledgeSource` above.
 */
export function uploadKnowledgeDocument(
  workspaceId: string,
  input: UploadKnowledgeDocumentInput,
): Promise<{ document: KnowledgeDocument; ingestion_job: KnowledgeIngestionJob }> {
  const formData = new FormData();
  formData.set("source_id", input.sourceId);
  formData.set("title", input.title);
  formData.set("file", input.file);
  return requestWithTimeout(
    (signal) =>
      apiClient.POST("/api/v1/workspaces/{workspace_id}/knowledge/documents/", {
        params: { path: { workspace_id: workspaceId } },
        // See the module doc comment: the generated multipart body type
        // cannot express a real `File`, so this is an explicit, narrow cast
        // at the one call site that needs it — never `any`/`ts-ignore`.
        body: formData as unknown as components["schemas"]["KnowledgeDocumentUpload"],
        bodySerializer: (body) => body,
        signal,
      }),
    UPLOAD_TIMEOUT_MS,
  ) as unknown as Promise<{ document: KnowledgeDocument; ingestion_job: KnowledgeIngestionJob }>;
}

/**
 * Only `failed` documents are retryable (knowledge/services.py
 * `retry_document`) — any other status returns a real 409 `conflict`. No
 * request body; the URL is the action (same pattern as Approve/Reject —
 * see features/approvals/api.ts).
 */
export function retryKnowledgeDocument(
  workspaceId: string,
  documentId: string,
): Promise<KnowledgeIngestionJob> {
  return requestWithTimeout((signal) =>
    apiClient.POST("/api/v1/workspaces/{workspace_id}/knowledge/documents/{document_id}/retry/", {
      params: { path: { workspace_id: workspaceId, document_id: documentId } },
      signal,
    }),
  );
}

/**
 * Real-time semantic search over this workspace's ready, active knowledge
 * chunks (`knowledge/retrieval/services.py search_knowledge`) — a POST, not
 * a GET: every call persists a real `RetrievalEvent` (+ one `RetrievalHit`
 * per returned result), so this is a genuine, telemetry-producing mutation,
 * never treated as a cacheable/automatically-retried read (see queries.ts).
 * Unlike Chunk 2's upload/source-create endpoints, the generated
 * `KnowledgeSearchRequest`/`KnowledgeSearchResponse` types are accurate —
 * no schema-gap cast needed here.
 */
export function fetchKnowledgeSearch(
  workspaceId: string,
  input: KnowledgeSearchRequestInput,
  signal?: AbortSignal,
): Promise<KnowledgeSearchResponse> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.POST("/api/v1/workspaces/{workspace_id}/knowledge/search/", {
          params: { path: { workspace_id: workspaceId } },
          body: {
            query: input.query,
            top_k: input.topK,
            source_ids: input.sourceId ? [input.sourceId] : undefined,
          },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}
