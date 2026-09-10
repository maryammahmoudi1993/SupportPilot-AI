/**
 * React Query hooks for the knowledge domain.
 *
 * Polling strategy (Phase 21 Chunk 2, master prompt Part D §16-18 — same
 * pattern as features/agent-runs/queries.ts `pollWhileNonTerminal`): only
 * the Document *detail* query polls, and only while that document's own
 * fetched `status` is non-terminal (`pending`/`queued`/`processing`).
 * `refetchInterval`'s callback reads the *latest fetched data* on every
 * scheduling decision, so a document that turns `ready`/`failed` between
 * polls stops being polled on the very next scheduling check, not one cycle
 * late — and `refetchIntervalInBackground: false` means a hidden tab or an
 * unmounted detail page polls nothing. The Documents *list* is deliberately
 * never polled (master prompt Part D §17 explicitly forbids "1 list query +
 * N detail polls" — and even a single bounded list-level poll would be a
 * second, compounded request stream underneath whatever an operator already
 * has open in a detail tab, for no signal that tab doesn't already carry):
 * an operator watching ingestion progress opens the one document they
 * uploaded/retried, exactly like AgentRun/Approval before it.
 */
import { useQuery } from "@tanstack/react-query";

import {
  fetchAllKnowledgeSourcesForFilter,
  fetchKnowledgeDocumentDetail,
  fetchKnowledgeDocumentList,
  fetchKnowledgeSourceDetail,
  fetchKnowledgeSourceList,
} from "@/features/knowledge/api";
import { knowledgeKeys } from "@/features/knowledge/query-keys";
import type {
  KnowledgeDocument,
  KnowledgeDocumentListParams,
  KnowledgeSource,
  KnowledgeSourceListParams,
  PaginatedKnowledgeDocumentList,
  PaginatedKnowledgeSourceList,
} from "@/features/knowledge/types";
import { isTerminalDocumentStatus } from "@/features/knowledge/types";
import type { ApiError } from "@/lib/api/errors";

const NO_WORKSPACE = "no-workspace";

/** Non-terminal documents are polled at this interval (ms) while the tab is visible. */
export const KNOWLEDGE_DOCUMENT_POLL_INTERVAL_MS = 5000;

/**
 * `refetchInterval` receives the query's latest state on every scheduling
 * decision (not just the render that set it up), so this correctly stops
 * polling the instant a fetch observes a terminal status — including across
 * a workspace switch, since a stale document's query is simply no longer
 * the active one being rendered (disjoint, workspace-scoped keys — see
 * query-keys.ts).
 */
export function pollWhileDocumentNonTerminal(query: {
  state: { data?: KnowledgeDocument };
}): number | false {
  const status = query.state.data?.status;
  if (!status || isTerminalDocumentStatus(status)) {
    return false;
  }
  return KNOWLEDGE_DOCUMENT_POLL_INTERVAL_MS;
}

export function useKnowledgeDocumentListQuery(
  workspaceId: string | null,
  params: KnowledgeDocumentListParams,
) {
  return useQuery<PaginatedKnowledgeDocumentList, ApiError>({
    queryKey: knowledgeKeys.documentList(workspaceId ?? NO_WORKSPACE, params),
    queryFn: ({ signal }) => fetchKnowledgeDocumentList(workspaceId as string, params, signal),
    enabled: workspaceId !== null,
  });
}

export function useKnowledgeDocumentDetailQuery(
  workspaceId: string | null,
  documentId: string | null,
) {
  return useQuery<KnowledgeDocument, ApiError>({
    queryKey: knowledgeKeys.documentDetail(workspaceId ?? NO_WORKSPACE, documentId ?? ""),
    queryFn: ({ signal }) =>
      fetchKnowledgeDocumentDetail(workspaceId as string, documentId as string, signal),
    enabled: workspaceId !== null && documentId !== null,
    refetchInterval: pollWhileDocumentNonTerminal,
    refetchIntervalInBackground: false,
  });
}

export function useKnowledgeSourceListQuery(
  workspaceId: string | null,
  params: KnowledgeSourceListParams,
) {
  return useQuery<PaginatedKnowledgeSourceList, ApiError>({
    queryKey: knowledgeKeys.sourceList(workspaceId ?? NO_WORKSPACE, params),
    queryFn: ({ signal }) => fetchKnowledgeSourceList(workspaceId as string, params, signal),
    enabled: workspaceId !== null,
  });
}

/** Powers the Documents list's "Source" filter — see api.ts for why this is one bounded call. */
export function useKnowledgeSourceFilterOptionsQuery(workspaceId: string | null) {
  return useQuery<PaginatedKnowledgeSourceList, ApiError>({
    queryKey: knowledgeKeys.sourceFilterOptions(workspaceId ?? NO_WORKSPACE),
    queryFn: ({ signal }) => fetchAllKnowledgeSourcesForFilter(workspaceId as string, signal),
    enabled: workspaceId !== null,
  });
}

export function useKnowledgeSourceDetailQuery(workspaceId: string | null, sourceId: string | null) {
  return useQuery<KnowledgeSource, ApiError>({
    queryKey: knowledgeKeys.sourceDetail(workspaceId ?? NO_WORKSPACE, sourceId ?? ""),
    queryFn: ({ signal }) =>
      fetchKnowledgeSourceDetail(workspaceId as string, sourceId as string, signal),
    enabled: workspaceId !== null && sourceId !== null,
  });
}
