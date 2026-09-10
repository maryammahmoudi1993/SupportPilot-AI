/**
 * Typed API boundary for the webhooks domain (Phase 22 Chunk 2 — endpoint
 * and delivery list/detail only; see types.ts for the mutation-deferral
 * decision).
 *
 * Schema gap (Category B, `ordering`/`search` — same shape as Integrations'
 * Chunk 1 gap in features/integrations/api.ts): the generated
 * `api_v1_workspaces_webhooks_endpoints_list`/`..._deliveries_list`
 * operations type `ordering`, `page`, `page_size`, `search` as query
 * params, but neither `WebhookEndpointListCreateView` nor
 * `WebhookDeliveryListView` (backend/webhooks/views.py) declares any
 * `filter_backends` at all — verified directly against both views. Both
 * lists are always ordered `-created_at, -id` (webhooks/selectors.py) and
 * cannot be filtered. Only `page` is real.
 */
import { apiClient } from "@/lib/api/client";
import { unwrap, withRequestTimeout } from "@/lib/api/request";
import type {
  PaginatedWebhookDeliveryList,
  PaginatedWebhookEndpointList,
  SafeWebhookDelivery,
  WebhookDeliveryListParams,
  WebhookEndpoint,
  WebhookEndpointListParams,
} from "@/features/webhooks/types";
import { toSafeWebhookDelivery } from "@/features/webhooks/types";
import type { paths } from "@/types/api";

type GeneratedEndpointListQuery = NonNullable<
  paths["/api/v1/workspaces/{workspace_id}/webhooks/endpoints/"]["get"]["parameters"]["query"]
>;
type EndpointListQuery = Pick<GeneratedEndpointListQuery, "page">;

function toEndpointListQuery(params: WebhookEndpointListParams): EndpointListQuery {
  const query: EndpointListQuery = {};
  if (params.page > 1) {
    query.page = params.page;
  }
  return query;
}

export function fetchWebhookEndpointList(
  workspaceId: string,
  params: WebhookEndpointListParams,
  signal?: AbortSignal,
): Promise<PaginatedWebhookEndpointList> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/webhooks/endpoints/", {
          params: {
            path: { workspace_id: workspaceId },
            query: toEndpointListQuery(params),
          },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}

export function fetchWebhookEndpointDetail(
  workspaceId: string,
  endpointId: string,
  signal?: AbortSignal,
): Promise<WebhookEndpoint> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/webhooks/endpoints/{endpoint_id}/", {
          params: { path: { workspace_id: workspaceId, endpoint_id: endpointId } },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}

type GeneratedDeliveryListQuery = NonNullable<
  paths["/api/v1/workspaces/{workspace_id}/webhooks/deliveries/"]["get"]["parameters"]["query"]
>;
type DeliveryListQuery = Pick<GeneratedDeliveryListQuery, "page">;

function toDeliveryListQuery(params: WebhookDeliveryListParams): DeliveryListQuery {
  const query: DeliveryListQuery = {};
  if (params.page > 1) {
    query.page = params.page;
  }
  return query;
}

export async function fetchWebhookDeliveryList(
  workspaceId: string,
  params: WebhookDeliveryListParams,
  signal?: AbortSignal,
): Promise<PaginatedWebhookDeliveryList> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/webhooks/deliveries/", {
          params: {
            path: { workspace_id: workspaceId },
            query: toDeliveryListQuery(params),
          },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}

export async function fetchWebhookDeliveryDetail(
  workspaceId: string,
  deliveryId: string,
  signal?: AbortSignal,
): Promise<SafeWebhookDelivery> {
  const delivery = await unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/webhooks/deliveries/{delivery_id}/", {
          params: { path: { workspace_id: workspaceId, delivery_id: deliveryId } },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
  return toSafeWebhookDelivery(delivery);
}
