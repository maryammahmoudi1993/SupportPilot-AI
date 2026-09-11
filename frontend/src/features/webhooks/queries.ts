/**
 * React Query hooks for the webhooks domain (Chunk 2 — read-only).
 *
 * Polling: only the Delivery *detail* query polls, and only while that
 * delivery's own fetched `status` is non-terminal (`pending`/`claimed`/
 * `retry_scheduled`) — same `refetchInterval`-reads-latest-data pattern as
 * features/knowledge/queries.ts `pollWhileDocumentNonTerminal`. The
 * Delivery *list* and the Endpoint list/detail are never polled — an
 * endpoint's own fields only change via a mutation this chunk doesn't
 * expose, and polling the list underneath an open, already-polling detail
 * tab would be exactly the "list + N detail polls" pattern master prompt
 * Part F §23 forbids. An operator watching a specific pending/retrying
 * delivery opens that one delivery's own detail, exactly like AgentRun/
 * KnowledgeDocument before it.
 */
import { useQuery } from "@tanstack/react-query";

import {
  fetchWebhookDeliveryDetail,
  fetchWebhookDeliveryList,
  fetchWebhookEndpointDetail,
  fetchWebhookEndpointList,
} from "@/features/webhooks/api";
import { webhookKeys } from "@/features/webhooks/query-keys";
import type {
  PaginatedWebhookDeliveryList,
  PaginatedWebhookEndpointList,
  SafeWebhookDelivery,
  WebhookDeliveryListParams,
  WebhookEndpoint,
  WebhookEndpointListParams,
} from "@/features/webhooks/types";
import { isTerminalDeliveryStatus } from "@/features/webhooks/types";
import type { ApiError } from "@/lib/api/errors";

const NO_WORKSPACE = "no-workspace";

/** Non-terminal deliveries are polled at this interval (ms) while the tab is visible. */
export const WEBHOOK_DELIVERY_POLL_INTERVAL_MS = 5000;

export function pollWhileDeliveryNonTerminal(query: {
  state: { data?: SafeWebhookDelivery };
}): number | false {
  const status = query.state.data?.status;
  if (!status || isTerminalDeliveryStatus(status)) {
    return false;
  }
  return WEBHOOK_DELIVERY_POLL_INTERVAL_MS;
}

export function useWebhookEndpointListQuery(
  workspaceId: string | null,
  params: WebhookEndpointListParams,
) {
  return useQuery<PaginatedWebhookEndpointList, ApiError>({
    queryKey: webhookKeys.endpointList(workspaceId ?? NO_WORKSPACE, params),
    queryFn: ({ signal }) => fetchWebhookEndpointList(workspaceId as string, params, signal),
    enabled: workspaceId !== null,
  });
}

export function useWebhookEndpointDetailQuery(
  workspaceId: string | null,
  endpointId: string | null,
) {
  return useQuery<WebhookEndpoint, ApiError>({
    queryKey: webhookKeys.endpointDetail(workspaceId ?? NO_WORKSPACE, endpointId ?? ""),
    queryFn: ({ signal }) =>
      fetchWebhookEndpointDetail(workspaceId as string, endpointId as string, signal),
    enabled: workspaceId !== null && endpointId !== null,
  });
}

export function useWebhookDeliveryListQuery(
  workspaceId: string | null,
  params: WebhookDeliveryListParams,
) {
  return useQuery<PaginatedWebhookDeliveryList, ApiError>({
    queryKey: webhookKeys.deliveryList(workspaceId ?? NO_WORKSPACE, params),
    queryFn: ({ signal }) => fetchWebhookDeliveryList(workspaceId as string, params, signal),
    enabled: workspaceId !== null,
  });
}

export function useWebhookDeliveryDetailQuery(
  workspaceId: string | null,
  deliveryId: string | null,
) {
  return useQuery<SafeWebhookDelivery, ApiError>({
    queryKey: webhookKeys.deliveryDetail(workspaceId ?? NO_WORKSPACE, deliveryId ?? ""),
    queryFn: ({ signal }) =>
      fetchWebhookDeliveryDetail(workspaceId as string, deliveryId as string, signal),
    enabled: workspaceId !== null && deliveryId !== null,
    refetchInterval: pollWhileDeliveryNonTerminal,
    refetchIntervalInBackground: false,
  });
}
