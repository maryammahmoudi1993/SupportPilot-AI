/**
 * Typed, workspace-scoped query key factory for the knowledge domain — same
 * policy as every other domain (see features/agent-runs/query-keys.ts).
 * Documents and sources are separate top-level entities (both real,
 * independently paginated) so each gets its own list/detail branch.
 */
import type {
  KnowledgeDocumentListParams,
  KnowledgeSourceListParams,
} from "@/features/knowledge/types";

export const knowledgeKeys = {
  all: (workspaceId: string) => ["workspaces", workspaceId, "knowledge"] as const,

  documents: (workspaceId: string) => [...knowledgeKeys.all(workspaceId), "documents"] as const,
  documentLists: (workspaceId: string) =>
    [...knowledgeKeys.documents(workspaceId), "list"] as const,
  documentList: (workspaceId: string, params: KnowledgeDocumentListParams) =>
    [...knowledgeKeys.documentLists(workspaceId), params] as const,
  documentDetails: (workspaceId: string) =>
    [...knowledgeKeys.documents(workspaceId), "detail"] as const,
  documentDetail: (workspaceId: string, documentId: string) =>
    [...knowledgeKeys.documentDetails(workspaceId), documentId] as const,

  sources: (workspaceId: string) => [...knowledgeKeys.all(workspaceId), "sources"] as const,
  sourceLists: (workspaceId: string) => [...knowledgeKeys.sources(workspaceId), "list"] as const,
  sourceList: (workspaceId: string, params: KnowledgeSourceListParams) =>
    [...knowledgeKeys.sourceLists(workspaceId), params] as const,
  /** The bounded "all sources" fetch used only to populate the Documents list's source filter. */
  sourceFilterOptions: (workspaceId: string) =>
    [...knowledgeKeys.sourceLists(workspaceId), "filter-options"] as const,
  sourceDetails: (workspaceId: string) =>
    [...knowledgeKeys.sources(workspaceId), "detail"] as const,
  sourceDetail: (workspaceId: string, sourceId: string) =>
    [...knowledgeKeys.sourceDetails(workspaceId), sourceId] as const,
};
