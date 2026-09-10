/**
 * Request-level mocks for the knowledge domain, mirroring the real backend
 * contract (backend/knowledge/views.py, knowledge/selectors.py,
 * knowledge/serializers.py, knowledge/services.py): workspace-scoped
 * storage, `source_id`/`status` filtering for documents, `search`/
 * `is_active` filtering for sources, DRF `PageNumberPagination`'s
 * `{count,next,previous,results}` envelope, and (Phase 21 Chunk 2) document
 * upload, source creation, and document retry — including the real
 * inactive-source/not-failed-document 409 `conflict` responses.
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

let nextId = 1;
function generateId(prefix: string): string {
  nextId += 1;
  return `${prefix}-${nextId}`;
}

export const knowledgeMockState = {
  documentsByWorkspace: {} as Record<string, KnowledgeDocumentFixture[]>,
  sourcesByWorkspace: {} as Record<string, KnowledgeSourceFixture[]>,
  documentListNetworkError: false,
  documentDetailCallCount: 0,
  documentCreateCallCount: 0,
  /** Simulates a request that never received a response (master prompt Part C §13). */
  uploadNetworkError: false,
  /** An artificial delay so an "in flight" window is actually observable in a test, rather than racing a same-tick MSW resolution — same pattern as approval-handlers.ts `decisionDelayMs`. */
  uploadDelayMs: 0,
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
  knowledgeMockState.documentDetailCallCount = 0;
  knowledgeMockState.documentCreateCallCount = 0;
  knowledgeMockState.uploadNetworkError = false;
  knowledgeMockState.uploadDelayMs = 0;
  nextId = 1;
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
      knowledgeMockState.documentDetailCallCount += 1;
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

  http.post(
    `${BASE}/api/v1/workspaces/:workspaceId/knowledge/documents/`,
    async ({ request, params }) => {
      knowledgeMockState.documentCreateCallCount += 1;
      if (knowledgeMockState.uploadDelayMs > 0) {
        await new Promise((resolve) => setTimeout(resolve, knowledgeMockState.uploadDelayMs));
      }
      if (knowledgeMockState.uploadNetworkError) {
        return HttpResponse.error();
      }
      const workspaceId = params.workspaceId as string;
      const formData = await request.formData();
      const sourceId = formData.get("source_id");
      const title = formData.get("title");
      const file = formData.get("file");
      // Presence-only check for `file`, not a shape/instanceof check: this
      // test environment's `fetch` (Node/undici, via MSW) and the browser
      // `File`/`Blob` classes React code and `userEvent.upload` construct
      // are different realms (see tests/setup.ts's File-polyfill comment) —
      // by the time a real multipart body round-trips through that pipeline
      // here, the parsed field can come back in a shape (e.g. a string
      // coercion) that never occurs in a real browser. This mock only needs
      // to prove the field was actually sent, not re-validate its type the
      // way the real backend does.
      if (typeof sourceId !== "string" || typeof title !== "string" || file === null) {
        return HttpResponse.json(
          { error: { code: "validation_error", message: "Invalid request." } },
          { status: 400 },
        );
      }
      const source = knowledgeMockState.sourcesByWorkspace[workspaceId]?.find(
        (s) => s.id === sourceId,
      );
      if (!source) {
        return HttpResponse.json(
          { error: { code: "not_found", message: "Knowledge source not found." } },
          { status: 404 },
        );
      }
      if (!source.is_active) {
        return HttpResponse.json(
          { error: { code: "conflict", message: "The selected knowledge source is not active." } },
          { status: 409 },
        );
      }
      const fileName = file instanceof File ? file.name : "upload";
      const fileType = file instanceof File ? file.type : "text/plain";
      const fileSize = file instanceof File ? file.size : 0;
      const document = makeKnowledgeDocumentFixture({
        id: generateId("doc"),
        source_id: source.id,
        source_name: source.name,
        title: title || fileName,
        original_filename: fileName,
        content_type: fileType || "text/plain",
        file_size: fileSize,
        status: "queued",
        extracted_char_count: 0,
        chunk_count: 0,
        last_ingested_at: null,
      });
      knowledgeMockState.documentsByWorkspace[workspaceId] = [
        document,
        ...(knowledgeMockState.documentsByWorkspace[workspaceId] ?? []),
      ];
      return HttpResponse.json(
        {
          document,
          ingestion_job: {
            id: generateId("job"),
            document_id: document.id,
            status: "queued",
            attempt_count: 0,
            started_at: null,
            finished_at: null,
            error_code: "",
            safe_error_message: "",
            extractor_version: "",
            chunker_version: "",
            embedding_provider: "",
            embedding_model: "",
            embedding_dimension: null,
            created_at: document.created_at,
            updated_at: document.created_at,
          },
        },
        { status: 201 },
      );
    },
  ),

  http.post(
    `${BASE}/api/v1/workspaces/:workspaceId/knowledge/documents/:documentId/retry/`,
    async ({ params }) => {
      const workspaceId = params.workspaceId as string;
      const documentId = params.documentId as string;
      const documents = knowledgeMockState.documentsByWorkspace[workspaceId] ?? [];
      const document = documents.find((d) => d.id === documentId);
      if (!document) {
        return HttpResponse.json(
          { error: { code: "not_found", message: "Knowledge document not found." } },
          { status: 404 },
        );
      }
      if (document.status !== "failed") {
        return HttpResponse.json(
          { error: { code: "conflict", message: "Only failed documents can be retried." } },
          { status: 409 },
        );
      }
      document.status = "queued";
      document.last_error_code = "";
      document.last_error_message_safe = "";
      return HttpResponse.json(
        {
          id: generateId("job"),
          document_id: document.id,
          status: "queued",
          attempt_count: 0,
          started_at: null,
          finished_at: null,
          error_code: "",
          safe_error_message: "",
          extractor_version: "",
          chunker_version: "",
          embedding_provider: "",
          embedding_model: "",
          embedding_dimension: null,
          created_at: document.created_at,
          updated_at: document.created_at,
        },
        { status: 202 },
      );
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

  http.post(
    `${BASE}/api/v1/workspaces/:workspaceId/knowledge/sources/`,
    async ({ request, params }) => {
      const workspaceId = params.workspaceId as string;
      const body = (await request.json()) as { name?: string; description?: string };
      if (!body.name || body.name.trim().length === 0) {
        return HttpResponse.json(
          { error: { code: "validation_error", message: "This field may not be blank." } },
          { status: 400 },
        );
      }
      const source = makeKnowledgeSourceFixture({
        id: generateId("source"),
        name: body.name,
        description: body.description ?? "",
      });
      knowledgeMockState.sourcesByWorkspace[workspaceId] = [
        source,
        ...(knowledgeMockState.sourcesByWorkspace[workspaceId] ?? []),
      ];
      return HttpResponse.json(source, { status: 201 });
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
