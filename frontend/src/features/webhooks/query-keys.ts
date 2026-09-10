/**
 * Typed, workspace-scoped query key factory for the webhooks domain — same
 * policy as every other domain (see features/integrations/query-keys.ts).
 * Nested under the same "integrations" root as connections (conceptually
 * `["workspaces", wsId, "integrations", "webhooks", "endpoints"|"deliveries", ...]`)
 * since Webhook Endpoints/Deliveries are a sub-surface of the same
 * Integrations product area (master prompt Part G §27), not a sibling
 * top-level domain — but each still gets its own list/detail branch so a
 * connection query invalidation can never accidentally touch webhook data
 * or vice versa.
 */
import type {
  WebhookDeliveryListParams,
  WebhookEndpointListParams,
} from "@/features/webhooks/types";

export const webhookKeys = {
  all: (workspaceId: string) =>
    ["workspaces", workspaceId, "integrations", "webhooks"] as const,

  endpoints: (workspaceId: string) => [...webhookKeys.all(workspaceId), "endpoints"] as const,
  endpointLists: (workspaceId: string) => [...webhookKeys.endpoints(workspaceId), "list"] as const,
  endpointList: (workspaceId: string, params: WebhookEndpointListParams) =>
    [...webhookKeys.endpointLists(workspaceId), params] as const,
  endpointDetails: (workspaceId: string) =>
    [...webhookKeys.endpoints(workspaceId), "detail"] as const,
  endpointDetail: (workspaceId: string, endpointId: string) =>
    [...webhookKeys.endpointDetails(workspaceId), endpointId] as const,

  deliveries: (workspaceId: string) => [...webhookKeys.all(workspaceId), "deliveries"] as const,
  deliveryLists: (workspaceId: string) =>
    [...webhookKeys.deliveries(workspaceId), "list"] as const,
  deliveryList: (workspaceId: string, params: WebhookDeliveryListParams) =>
    [...webhookKeys.deliveryLists(workspaceId), params] as const,
  deliveryDetails: (workspaceId: string) =>
    [...webhookKeys.deliveries(workspaceId), "detail"] as const,
  deliveryDetail: (workspaceId: string, deliveryId: string) =>
    [...webhookKeys.deliveryDetails(workspaceId), deliveryId] as const,
};
