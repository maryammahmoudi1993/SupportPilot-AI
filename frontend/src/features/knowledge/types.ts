/**
 * Knowledge/RAG domain types (Phase 21 Chunk 1 — read-only foundation).
 * `KnowledgeDocument` and `KnowledgeSource` are the two real, public entities
 * (backend/knowledge/models.py `KnowledgeDocument`/`KnowledgeSource`,
 * serialized by backend/knowledge/serializers.py). `KnowledgeChunk`,
 * `KnowledgeIngestionJob`, and retrieval (`RetrievalEvent`/`RetrievalHit`)
 * are real backend concepts too, but this chunk does not read or render
 * them: a document's own `status`/`last_ingested_at`/`last_error_code`/
 * `chunk_count` fields already carry every ingestion signal Chunk 1 needs,
 * and fetching a separate ingestion job or chunk list per document would
 * mean either guessing an ID the document response never includes or an
 * N+1 request pattern (master prompt Part G §33-34) — both out of scope
 * until Chunk 2/3.
 */
import type { components } from "@/types/api";

export type KnowledgeDocument = components["schemas"]["KnowledgeDocument"];
export type KnowledgeDocumentStatusValue = components["schemas"]["KnowledgeDocumentStatusEnum"];
export type PaginatedKnowledgeDocumentList =
  components["schemas"]["PaginatedKnowledgeDocumentList"];

export type KnowledgeSource = components["schemas"]["KnowledgeSource"];
export type KnowledgeSourceTypeValue = components["schemas"]["KnowledgeSourceTypeEnum"];
export type PaginatedKnowledgeSourceList = components["schemas"]["PaginatedKnowledgeSourceList"];

/**
 * The backend's real terminal ingestion states (backend/knowledge/models.py
 * `KnowledgeDocumentStatus`) — `ready` and `failed` never change on their
 * own; `pending`/`queued`/`processing` can still transition. Mirrored here
 * (not imported — frontend/backend are separate deployables) so a future
 * polling feature (Chunk 2) has a single source of truth for "is this worth
 * watching," and so Chunk 1's detail view can label a state as settled or
 * still moving without inventing a percentage/ETA (master prompt Part A §10).
 */
const TERMINAL_DOCUMENT_STATUSES: ReadonlySet<KnowledgeDocumentStatusValue> = new Set([
  "ready",
  "failed",
]);

export function isTerminalDocumentStatus(status: KnowledgeDocumentStatusValue): boolean {
  return TERMINAL_DOCUMENT_STATUSES.has(status);
}

/** `"all"` omits the corresponding filter from the request entirely. */
export type DocumentStatusFilter = "all" | KnowledgeDocumentStatusValue;

/**
 * Real, backend-tested filters only (knowledge/selectors.py
 * `document_list_for_workspace`): `source_id` and `status`. There is no
 * `search` filter for documents — see api.ts for the generated-schema gap.
 */
export interface KnowledgeDocumentListParams {
  page: number;
  sourceId: string | "all";
  status: DocumentStatusFilter;
}

export const DEFAULT_KNOWLEDGE_DOCUMENT_LIST_PARAMS: KnowledgeDocumentListParams = {
  page: 1,
  sourceId: "all",
  status: "all",
};

/** `"all"` omits the corresponding filter from the request entirely. */
export type SourceActiveFilter = "all" | "true" | "false";

/**
 * Real, backend-tested filters only (knowledge/selectors.py
 * `source_list_for_workspace`): `search` (name/description, case-insensitive
 * contains) and `is_active`.
 */
export interface KnowledgeSourceListParams {
  page: number;
  search: string;
  isActive: SourceActiveFilter;
}

export const DEFAULT_KNOWLEDGE_SOURCE_LIST_PARAMS: KnowledgeSourceListParams = {
  page: 1,
  search: "",
  isActive: "all",
};
