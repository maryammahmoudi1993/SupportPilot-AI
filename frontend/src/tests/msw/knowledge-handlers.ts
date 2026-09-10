/**
 * Request-level mocks for the knowledge domain (read-only this chunk),
 * mirroring the real backend contract (backend/knowledge/views.py,
 * knowledge/selectors.py, knowledge/serializers.py): workspace-scoped
 * storage, `source_id`/`status` filtering for documents, `search`/
 * `is_active` filtering for sources, DRF `PageNumberPagination`'s
 * `{count,next,previous,results}` envelope.
 */
import { HttpResponse, http } from "msw";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface KnowledgeSourceFixture {
  id: string;
  name: string;
  description?: string;
  source_type: "upload" | "manual";
  is_active: boolean;
  metadata: unknown;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeDocumentFixture {
  id: string;
  source_id: string;
  source_name: string;
  title: string;
  original_filename: string;
  content_type: string;
  file_size: number;
  status: "pending" | "queued" | "processing" | "ready" | "failed";
  is_active: boolean;
  extracted_char_count: number;
  chunk_count: number;
  last_ingested_at: string | null;
  last_error_code: string;
  last_error_message_safe: string;
  metadata: unknown;
  created_at: string;
  updated_at: string;
}

export function makeKnowledgeSourceFixture(
  overrides: Partial<KnowledgeSourceFixture> & { id: string; name: string },
): KnowledgeSourceFixture {
  return {
    description: "",
    source_type: "upload",
    is_active: true,
    metadata: {},
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export function makeKnowledgeDocumentFixture(
  overrides: Partial<KnowledgeDocumentFixture> & {
    id: string;
    source_id: string;
    source_name: string;
    title: string;
  },
): KnowledgeDocumentFixture {
  return {
    original_filename: "document.txt",
    content_type: "text/plain",
    file_size: 1024,
    status: "ready",
    is_active: true,
    extracted_char_count: 500,
    chunk_count: 3,
    last_ingested_at: "2026-01-01T00:05:00Z",
    last_error_code: "",
    last_error_message_safe: "",
    metadata: {},
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:05:00Z",
    ...overrides,
  };
}

export const knowledgeMockState = {
  documentsByWorkspace: {} as Record<string, KnowledgeDocumentFixture[]>,
  sourcesByWorkspace: {} as Record<string, KnowledgeSourceFixture[]>,
  documentListNetworkError: false,
};

export function seedKnowledgeDocuments(
  workspaceId: string,
  documents: KnowledgeDocumentFixture[],
): void {
  knowledgeMockState.documentsByWorkspace[workspaceId] = documents;
}

export function seedKnowledgeSources(workspaceId: string, sources: KnowledgeSourceFixture[]): void {
  knowledgeMockState.sourcesByWorkspace[workspaceId] = sources;
}

export function resetKnowledgeMockState(): void {
  knowledgeMockState.documentsByWorkspace = {};
  knowledgeMockState.sourcesByWorkspace = {};
  knowledgeMockState.documentListNetworkError = false;
}

function paginate<T>(items: T[], url: URL) {
  const page = Number(url.searchParams.get("page") ?? "1");
  const pageSize = Number(url.searchParams.get("page_size") ?? "50");
  const count = items.length;
  const start = (page - 1) * pageSize;
  const results = items.slice(start, start + pageSize);
  const hasNext = start + pageSize < count;
  const hasPrevious = page > 1;
  const nextUrl = hasNext ? `${url.origin}${url.pathname}?page=${page + 1}` : null;
  const previousUrl = hasPrevious
    ? `${url.origin}${url.pathname}${page - 1 > 1 ? `?page=${page - 1}` : ""}`
    : null;
  return { count, next: nextUrl, previous: previousUrl, results };
}

export const knowledgeHandlers = [
  http.get(
    `${BASE}/api/v1/workspaces/:workspaceId/knowledge/documents/`,
    async ({ request, params }) => {
      if (knowledgeMockState.documentListNetworkError) {
        return HttpResponse.error();
      }
      const workspaceId = params.workspaceId as string;
      const url = new URL(request.url);
      const sourceId = url.searchParams.get("source_id");
      const status = url.searchParams.get("status");
      let results = knowledgeMockState.documentsByWorkspace[workspaceId] ?? [];
      if (sourceId) {
        results = results.filter((document) => document.source_id === sourceId);
      }
      if (status) {
        results = results.filter((document) => document.status === status);
      }
      return HttpResponse.json(paginate(results, url));
    },
  ),

  http.get(
    `${BASE}/api/v1/workspaces/:workspaceId/knowledge/documents/:documentId/`,
    async ({ params }) => {
      const workspaceId = params.workspaceId as string;
      const documentId = params.documentId as string;
      const document = knowledgeMockState.documentsByWorkspace[workspaceId]?.find(
        (d) => d.id === documentId,
      );
      if (!document) {
        return HttpResponse.json(
          { error: { code: "not_found", message: "Knowledge document not found." } },
          { status: 404 },
        );
      }
      return HttpResponse.json(document);
    },
  ),

  http.get(
    `${BASE}/api/v1/workspaces/:workspaceId/knowledge/sources/`,
    async ({ request, params }) => {
      const workspaceId = params.workspaceId as string;
      const url = new URL(request.url);
      const search = url.searchParams.get("search")?.toLowerCase();
      const isActive = url.searchParams.get("is_active");
      let results = knowledgeMockState.sourcesByWorkspace[workspaceId] ?? [];
      if (search) {
        results = results.filter(
          (source) =>
            source.name.toLowerCase().includes(search) ||
            (source.description ?? "").toLowerCase().includes(search),
        );
      }
      if (isActive !== null) {
        const wantActive = isActive === "true";
        results = results.filter((source) => source.is_active === wantActive);
      }
      return HttpResponse.json(paginate(results, url));
    },
  ),

  http.get(
    `${BASE}/api/v1/workspaces/:workspaceId/knowledge/sources/:sourceId/`,
    async ({ params }) => {
      const workspaceId = params.workspaceId as string;
      const sourceId = params.sourceId as string;
      const source = knowledgeMockState.sourcesByWorkspace[workspaceId]?.find(
        (s) => s.id === sourceId,
      );
      if (!source) {
        return HttpResponse.json(
          { error: { code: "not_found", message: "Knowledge source not found." } },
          { status: 404 },
        );
      }
      return HttpResponse.json(source);
    },
  ),
];
