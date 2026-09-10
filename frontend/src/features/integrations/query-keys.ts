/**
 * Typed, workspace-scoped query key factory for the integrations domain —
 * same policy as every other domain (see features/knowledge/query-keys.ts).
 * Every branch includes the workspace ID so a workspace switch can never
 * read another workspace's connections out of the cache, and so a
 * late-arriving response for a since-abandoned workspace can only ever
 * resolve into that workspace's own, no-longer-rendered key.
 */
import type { IntegrationConnectionListParams } from "@/features/integrations/types";

export const integrationKeys = {
  all: (workspaceId: string) => ["workspaces", workspaceId, "integrations"] as const,

  connections: (workspaceId: string) =>
    [...integrationKeys.all(workspaceId), "connections"] as const,
  connectionLists: (workspaceId: string) =>
    [...integrationKeys.connections(workspaceId), "list"] as const,
  connectionList: (workspaceId: string, params: IntegrationConnectionListParams) =>
    [...integrationKeys.connectionLists(workspaceId), params] as const,
  connectionDetails: (workspaceId: string) =>
    [...integrationKeys.connections(workspaceId), "detail"] as const,
  connectionDetail: (workspaceId: string, connectionId: string) =>
    [...integrationKeys.connectionDetails(workspaceId), connectionId] as const,
};
