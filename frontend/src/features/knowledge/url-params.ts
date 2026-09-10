/**
 * Shareable/restorable URL query-string state for the Knowledge list — same
 * pattern and untrusted-input posture as features/handoffs/url-params.ts.
 * One route (`/app/knowledge`) hosts three real tabs (Documents/Sources/
 * Search, see knowledge-list-page.tsx); `tab` selects between them and each
 * tab keeps its own page/filter params so switching tabs never clobbers the
 * other's state in the URL. The Search tab's own query text/filters are
 * deliberately NOT part of the URL (master prompt Part R §66 — no clear
 * product reason to make a submitted search text shareable/bookmarkable,
 * and every search is already a persisted, telemetry-producing request) —
 * only which tab is active lives here.
 */
import type {
  DocumentStatusFilter,
  KnowledgeDocumentListParams,
  KnowledgeSourceListParams,
  SourceActiveFilter,
} from "@/features/knowledge/types";
import {
  DEFAULT_KNOWLEDGE_DOCUMENT_LIST_PARAMS,
  DEFAULT_KNOWLEDGE_SOURCE_LIST_PARAMS,
} from "@/features/knowledge/types";

const VALID_STATUSES: readonly string[] = ["pending", "queued", "processing", "ready", "failed"];
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type KnowledgeTab = "documents" | "sources" | "search";

export function parseKnowledgeTab(searchParams: URLSearchParams): KnowledgeTab {
  const raw = searchParams.get("tab");
  if (raw === "sources") {
    return "sources";
  }
  if (raw === "search") {
    return "search";
  }
  return "documents";
}

function parsePage(raw: string | null, fallback: number): number {
  if (!raw || !/^[1-9]\d*$/.test(raw)) {
    return fallback;
  }
  const page = Number(raw);
  return Number.isSafeInteger(page) ? page : fallback;
}

function parseStatus(raw: string | null): DocumentStatusFilter {
  return raw && VALID_STATUSES.includes(raw) ? (raw as DocumentStatusFilter) : "all";
}

function parseSourceId(raw: string | null): string | "all" {
  return raw && UUID_PATTERN.test(raw) ? raw : "all";
}

export function parseKnowledgeDocumentListParams(
  searchParams: URLSearchParams,
): KnowledgeDocumentListParams {
  return {
    page: parsePage(searchParams.get("page"), DEFAULT_KNOWLEDGE_DOCUMENT_LIST_PARAMS.page),
    sourceId: parseSourceId(searchParams.get("source")),
    status: parseStatus(searchParams.get("status")),
  };
}

export function buildKnowledgeDocumentListQueryString(params: KnowledgeDocumentListParams): string {
  const search = new URLSearchParams();
  if (params.page > 1) {
    search.set("page", String(params.page));
  }
  if (params.sourceId !== "all") {
    search.set("source", params.sourceId);
  }
  if (params.status !== "all") {
    search.set("status", params.status);
  }
  const query = search.toString();
  return query.length > 0 ? `?${query}` : "";
}

function parseIsActive(raw: string | null): SourceActiveFilter {
  return raw === "true" || raw === "false" ? raw : "all";
}

export function parseKnowledgeSourceListParams(
  searchParams: URLSearchParams,
): KnowledgeSourceListParams {
  return {
    page: parsePage(searchParams.get("page"), DEFAULT_KNOWLEDGE_SOURCE_LIST_PARAMS.page),
    search: searchParams.get("q") ?? "",
    isActive: parseIsActive(searchParams.get("is_active")),
  };
}

export function buildKnowledgeSourceListQueryString(params: KnowledgeSourceListParams): string {
  const search = new URLSearchParams();
  search.set("tab", "sources");
  if (params.page > 1) {
    search.set("page", String(params.page));
  }
  if (params.search.trim().length > 0) {
    search.set("q", params.search.trim());
  }
  if (params.isActive !== "all") {
    search.set("is_active", params.isActive);
  }
  return `?${search.toString()}`;
}
