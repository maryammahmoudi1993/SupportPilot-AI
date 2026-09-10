/**
 * React Query hooks for the knowledge domain. No polling: Chunk 1 renders
 * only a document's own persisted status snapshot (master prompt Part A
 * §10 forbids inventing a progress percentage), so there is nothing to poll
 * toward — bounded status polling for a non-terminal document belongs to
 * Chunk 2, once ingestion is actually triggerable from this frontend.
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
import type { ApiError } from "@/lib/api/errors";

const NO_WORKSPACE = "no-workspace";

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
