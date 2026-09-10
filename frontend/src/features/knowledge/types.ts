/**
 * Knowledge/RAG domain types. `KnowledgeDocument` and `KnowledgeSource` are
 * the two real, public entities (backend/knowledge/models.py
 * `KnowledgeDocument`/`KnowledgeSource`, serialized by
 * backend/knowledge/serializers.py). `KnowledgeChunk` and retrieval
 * (`RetrievalEvent`/`RetrievalHit`) are real backend concepts too, but no
 * chunk implemented so far reads or renders them — out of scope until
 * Chunk 3 (retrieval preview).
 *
 * `KnowledgeIngestionJob` (Chunk 2) has a real, public, but never-directly-
 * fetched-here GET endpoint (`GET .../knowledge/ingestion-jobs/{id}/`) — it
 * is only ever read as the upload/retry response body, never polled or
 * listed separately: a document's own `status`/`last_ingested_at`/
 * `last_error_code`/`chunk_count` fields already carry every ingestion
 * signal the UI needs, and polling a second, separate job resource per
 * document would be exactly the N+1/compounded-polling pattern master
 * prompt Part D §17 and Part L §40 forbid.
 */
import type { components } from "@/types/api";

export type KnowledgeDocument = components["schemas"]["KnowledgeDocument"];
export type KnowledgeDocumentStatusValue = components["schemas"]["KnowledgeDocumentStatusEnum"];
export type PaginatedKnowledgeDocumentList =
  components["schemas"]["PaginatedKnowledgeDocumentList"];

export type KnowledgeIngestionJob = components["schemas"]["KnowledgeIngestionJob"];

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

/**
 * The backend's real knowledge-management roles (knowledge/permissions.py
 * `CanManageKnowledge.KNOWLEDGE_MANAGEMENT_ROLES`) — mirrored here (not
 * imported — frontend/backend are separate deployables), same pattern as
 * `HUMAN_HANDOFF_ACTIVE_STATUSES` in features/handoffs/types.ts. Used only
 * to decide whether to *show* upload/create-source/retry controls at all;
 * the backend re-derives and re-enforces this from the caller's current DB
 * membership on every write regardless of what the UI renders.
 */
const KNOWLEDGE_MANAGEMENT_ROLES: ReadonlySet<string> = new Set([
  "owner",
  "admin",
  "support_manager",
]);

export function canManageKnowledge(role: string | undefined): boolean {
  return role !== undefined && KNOWLEDGE_MANAGEMENT_ROLES.has(role);
}

/**
 * The only document state the real retry endpoint accepts (knowledge/
 * services.py `retry_document`: "Only failed documents can be retried.",
 * a real 409 `conflict` for any other status) — mirrored here so the UI
 * never renders a Retry control the backend would just reject.
 */
export function isRetryableDocumentStatus(status: KnowledgeDocumentStatusValue): boolean {
  return status === "failed";
}

/**
 * Real, backend-tested upload constraints (backend/knowledge/ingestion/
 * validators.py `validate_upload`, config/settings.py
 * `KNOWLEDGE_ALLOWED_CONTENT_TYPES`/`KNOWLEDGE_MAX_UPLOAD_BYTES`) — mirrored
 * here for client-side UX only (accept attribute, a friendly pre-check
 * message). Neither value is exposed by any public API field; the backend
 * remains the sole authority and re-validates every upload regardless of
 * what the client pre-checks. If these constants drift from the real
 * backend settings, only the UX degrades (a client-rejected file the
 * backend would have accepted, or vice versa needing a server round trip)
 * — never a security assumption.
 */
export const KNOWLEDGE_ACCEPTED_CONTENT_TYPES: Readonly<Record<string, readonly string[]>> = {
  "text/plain": [".txt"],
  "text/markdown": [".md", ".markdown"],
  "application/pdf": [".pdf"],
};

export const KNOWLEDGE_ACCEPTED_FILE_EXTENSIONS: readonly string[] = Object.values(
  KNOWLEDGE_ACCEPTED_CONTENT_TYPES,
).flat();

export const KNOWLEDGE_MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

/** Real request fields only (knowledge/serializers.py `KnowledgeDocumentUploadSerializer`). */
export interface UploadKnowledgeDocumentInput {
  sourceId: string;
  title: string;
  file: File;
}

/** Real request fields only (knowledge/serializers.py `KnowledgeSourceWriteSerializer`) — a
 * deliberately minimal subset: this chunk creates a source only to unblock upload when none
 * exists yet, never a full source-management form (master prompt Part I §34). */
export interface CreateKnowledgeSourceInput {
  name: string;
  description?: string;
}
