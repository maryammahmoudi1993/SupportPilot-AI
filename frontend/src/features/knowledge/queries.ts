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
  fetchKnowledgeSearch,
  fetchKnowledgeSourceDetail,
  fetchKnowledgeSourceList,
} from "@/features/knowledge/api";
import { knowledgeKeys } from "@/features/knowledge/query-keys";
import type {
  KnowledgeDocument,
  KnowledgeDocumentListParams,
  KnowledgeSearchRequestInput,
  KnowledgeSearchResponse,
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

/**
 * Retrieval preview (Chunk 3). Deliberately NOT an ordinary `useQuery` keyed
 * by the request's content — search is a telemetry-producing POST (every
 * call persists a real `RetrievalEvent`, master prompt Part H §32), not a
 * cacheable list, so:
 *
 * - `enabled: false` — this query never fires on its own (mount,
 *   `queryKey` change, window focus, reconnect); the only way it ever runs
 *   is an explicit `refetch()` call from the search form's submit handler
 *   (master prompt Part J §41 — "one explicit search: one retrieval
 *   request").
 * - `retry: 0` — an automatic retry would silently create a second,
 *   user-invisible `RetrievalEvent` for the same submitted search.
 * - the query key is a single "current search" slot per workspace (see
 *   `knowledgeKeys.retrievalCurrent`), not one entry per distinct request —
 *   which is exactly what makes an in-flight workspace switch safe without
 *   any extra bookkeeping: a response for Workspace A's request can only
 *   ever resolve into A's slot. The component reading the *current* active
 *   workspace's slot is, at that point, already reading a different (empty,
 *   or previously-cleared) key — so a late A response can never render
 *   under B (master prompt Part I §37), and switching back to A later
 *   starts a fresh search rather than resurrecting a stale one.
 * - `requestRef` (not a state variable) is what the actual submitted
 *   request comes from: `queryFn` reads `requestRef.current` at *call*
 *   time, not at the time this hook's closure was created, so updating the
 *   ref and calling `refetch()` in the same event handler always uses the
 *   just-submitted request — no stale-closure/second-click bug, and no
 *   `useEffect` needed to "sync" state into the query.
 */
export function useKnowledgeSearchQuery(
  workspaceId: string,
  requestRef: { current: KnowledgeSearchRequestInput | null },
) {
  return useQuery<KnowledgeSearchResponse, ApiError>({
    queryKey: knowledgeKeys.retrievalCurrent(workspaceId),
    queryFn: ({ signal }) => {
      const request = requestRef.current;
      if (!request) {
        // Unreachable in practice: the form only ever calls `refetch()`
        // after setting `requestRef.current` — this guards the type only.
        return Promise.reject(new Error("No search has been submitted yet."));
      }
      return fetchKnowledgeSearch(workspaceId, request, signal);
    },
    enabled: false,
    retry: 0,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    refetchOnReconnect: false,
  });
}
