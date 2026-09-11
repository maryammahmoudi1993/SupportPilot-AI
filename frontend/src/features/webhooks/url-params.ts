/**
 * Shareable/restorable URL query-string state for the Webhook Endpoints and
 * Deliveries tabs on `/app/integrations` — same pattern as
 * features/integrations/url-params.ts. Only `page` is real for either list
 * (see api.ts's schema-gap note: no filter/search/ordering exists for
 * either).
 */
import type {
  WebhookDeliveryListParams,
  WebhookEndpointListParams,
} from "@/features/webhooks/types";
import {
  DEFAULT_WEBHOOK_DELIVERY_LIST_PARAMS,
  DEFAULT_WEBHOOK_ENDPOINT_LIST_PARAMS,
} from "@/features/webhooks/types";

function parsePage(raw: string | null, fallback: number): number {
  if (!raw || !/^[1-9]\d*$/.test(raw)) {
    return fallback;
  }
  const page = Number(raw);
  return Number.isSafeInteger(page) ? page : fallback;
}

export function parseWebhookEndpointListParams(
  searchParams: URLSearchParams,
): WebhookEndpointListParams {
  return { page: parsePage(searchParams.get("page"), DEFAULT_WEBHOOK_ENDPOINT_LIST_PARAMS.page) };
}

export function buildWebhookEndpointListQueryString(params: WebhookEndpointListParams): string {
  const search = new URLSearchParams();
  search.set("tab", "webhooks");
  if (params.page > 1) {
    search.set("page", String(params.page));
  }
  return `?${search.toString()}`;
}

export function parseWebhookDeliveryListParams(
  searchParams: URLSearchParams,
): WebhookDeliveryListParams {
  return { page: parsePage(searchParams.get("page"), DEFAULT_WEBHOOK_DELIVERY_LIST_PARAMS.page) };
}

export function buildWebhookDeliveryListQueryString(params: WebhookDeliveryListParams): string {
  const search = new URLSearchParams();
  search.set("tab", "deliveries");
  if (params.page > 1) {
    search.set("page", String(params.page));
  }
  return `?${search.toString()}`;
}
