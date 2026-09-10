/**
 * Typed API boundary for the integrations domain (Phase 22 Chunk 1 —
 * connections list/detail only, see types.ts for the mutation-deferral
 * decision).
 *
 * Schema gap (Category B, `ordering`/`search` — same shape as knowledge's
 * document-list gap in features/knowledge/api.ts): the generated
 * `api_v1_workspaces_integrations_list` operation types `ordering`, `page`,
 * `page_size`, `search` as query params, but `IntegrationConnectionListCreateView`
 * (backend/integrations/views.py) declares no `filter_backends` and no
 * `ordering_fields` at all — verified directly against the view. `ordering`
 * and `search` are schema-only/dead; the list is always ordered
 * `provider, id` (integrations/selectors.py `connection_list_for_workspace`)
 * and cannot be filtered. Only `page` (and, in principle, `page_size`, not
 * exposed by this chunk's UI) is real — DRF's `PageNumberPagination` reads
 * it directly from the request, independent of any filter backend.
 *
 * Schema gap (Category B, create response — same shape as knowledge's
 * source/document create in features/knowledge/api.ts): the generated
 * `api_v1_workspaces_integrations_create` operation types its 201 response
 * as `IntegrationConnectionCreate` (the *request* shape) rather than the
 * real response body — verified against integrations/views.py
 * `IntegrationConnectionListCreateView.create`, which returns
 * `IntegrationConnectionSerializer(connection).data`. Not exercised by this
 * chunk (create is deferred — see types.ts), documented here as a known gap
 * for whichever later chunk implements it.
 */
import { apiClient } from "@/lib/api/client";
import { unwrap, withRequestTimeout } from "@/lib/api/request";
import type {
  IntegrationConnection,
  IntegrationConnectionListParams,
  PaginatedIntegrationConnectionList,
} from "@/features/integrations/types";
import type { paths } from "@/types/api";

type GeneratedConnectionListQuery = NonNullable<
  paths["/api/v1/workspaces/{workspace_id}/integrations/"]["get"]["parameters"]["query"]
>;

type ConnectionListQuery = Pick<GeneratedConnectionListQuery, "page">;

function toConnectionListQuery(params: IntegrationConnectionListParams): ConnectionListQuery {
  const query: ConnectionListQuery = {};
  if (params.page > 1) {
    query.page = params.page;
  }
  return query;
}

export function fetchIntegrationConnectionList(
  workspaceId: string,
  params: IntegrationConnectionListParams,
  signal?: AbortSignal,
): Promise<PaginatedIntegrationConnectionList> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/integrations/", {
          params: {
            path: { workspace_id: workspaceId },
            query: toConnectionListQuery(params),
          },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}

export function fetchIntegrationConnectionDetail(
  workspaceId: string,
  connectionId: string,
  signal?: AbortSignal,
): Promise<IntegrationConnection> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/integrations/{connection_id}/", {
          params: { path: { workspace_id: workspaceId, connection_id: connectionId } },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}
