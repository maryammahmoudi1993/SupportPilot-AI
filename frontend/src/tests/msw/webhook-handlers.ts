/**
 * Request-level mocks for the webhooks domain (Phase 22 Chunk 2), mirroring
 * the real backend contract (backend/webhooks/views.py, webhooks/
 * selectors.py, webhooks/serializers.py): workspace-scoped storage, no
 * filter/search/ordering support (list/detail only — see
 * features/webhooks/api.ts's schema-gap note), DRF
 * `PageNumberPagination`'s `{count,next,previous,results}` envelope, and
 * the real 404 tenant-hiding contract for both a nonexistent and a
 * foreign-workspace endpoint/delivery.
 */
import { HttpResponse, http } from "msw";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface WebhookEndpointFixture {
  id: string;
  name: string;
  url: string;
  status: "active" | "disabled";
  subscribed_event_types: string[];
  secret_configured: boolean;
  secret_created_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface WebhookDeliveryFixture {
  delivery_id: string;
  event_id: string;
  event_type: string;
  endpoint_id: string;
  endpoint_name: string;
  status: string;
  attempt_count: number;
  max_attempts: number;
  next_attempt_at: string;
  last_error_code: string;
  last_http_status: number | null;
  delivered_at: string | null;
  failed_at: string | null;
  created_at: string;
}

export function makeWebhookEndpointFixture(
  overrides: Partial<WebhookEndpointFixture> & { id: string; name: string },
): WebhookEndpointFixture {
  return {
    url: "https://example.com/hooks/supportpilot",
    status: "active",
    subscribed_event_types: ["approval.requested"],
    secret_configured: true,
    secret_created_at: "2026-01-01T00:00:00Z",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export function makeWebhookDeliveryFixture(
  overrides: Partial<WebhookDeliveryFixture> & {
    delivery_id: string;
    endpoint_id: string;
    endpoint_name: string;
  },
): WebhookDeliveryFixture {
  return {
    event_id: "event-1",
    event_type: "approval.requested",
    status: "delivered",
    attempt_count: 1,
    max_attempts: 5,
    next_attempt_at: "2026-01-01T00:00:00Z",
    last_error_code: "",
    last_http_status: 200,
    delivered_at: "2026-01-01T00:00:05Z",
    failed_at: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export const webhookMockState = {
  endpointsByWorkspace: {} as Record<string, WebhookEndpointFixture[]>,
  deliveriesByWorkspace: {} as Record<string, WebhookDeliveryFixture[]>,
  endpointListNetworkError: false,
  deliveryListNetworkError: false,
  deliveryDetailCallCount: 0,
};

export function seedWebhookEndpoints(
  workspaceId: string,
  endpoints: WebhookEndpointFixture[],
): void {
  webhookMockState.endpointsByWorkspace[workspaceId] = endpoints;
}

export function seedWebhookDeliveries(
  workspaceId: string,
  deliveries: WebhookDeliveryFixture[],
): void {
  webhookMockState.deliveriesByWorkspace[workspaceId] = deliveries;
}

export function resetWebhookMockState(): void {
  webhookMockState.endpointsByWorkspace = {};
  webhookMockState.deliveriesByWorkspace = {};
  webhookMockState.endpointListNetworkError = false;
  webhookMockState.deliveryListNetworkError = false;
  webhookMockState.deliveryDetailCallCount = 0;
}

function paginate<T>(items: T[], url: URL) {
  const page = Number(url.searchParams.get("page") ?? "1");
  const pageSize = Number(url.searchParams.get("page_size") ?? "50");
  const count = items.length;
  const start = (page - 1) * pageSize;
  const results = items.slice(start, start + pageSize);
  const hasNext = start + pageSize < count;
  const hasPrevious = page > 1;
  const nextUrl = hasNext ? `${url.origin}${url.pathname}?page=${page + 1}` : null;
  const previousUrl = hasPrevious
    ? `${url.origin}${url.pathname}${page - 1 > 1 ? `?page=${page - 1}` : ""}`
    : null;
  return { count, next: nextUrl, previous: previousUrl, results };
}

export const webhookHandlers = [
  http.get(`${BASE}/api/v1/workspaces/:workspaceId/webhooks/endpoints/`, async ({ request, params }) => {
    if (webhookMockState.endpointListNetworkError) {
      return HttpResponse.error();
    }
    const workspaceId = params.workspaceId as string;
    const url = new URL(request.url);
    const results = webhookMockState.endpointsByWorkspace[workspaceId] ?? [];
    return HttpResponse.json(paginate(results, url));
  }),

  http.get(
    `${BASE}/api/v1/workspaces/:workspaceId/webhooks/endpoints/:endpointId/`,
    async ({ params }) => {
      const workspaceId = params.workspaceId as string;
      const endpointId = params.endpointId as string;
      const endpoint = webhookMockState.endpointsByWorkspace[workspaceId]?.find(
        (e) => e.id === endpointId,
      );
      if (!endpoint) {
        return HttpResponse.json(
          { error: { code: "not_found", message: "Webhook endpoint not found." } },
          { status: 404 },
        );
      }
      return HttpResponse.json(endpoint);
    },
  ),

  http.get(`${BASE}/api/v1/workspaces/:workspaceId/webhooks/deliveries/`, async ({ request, params }) => {
    if (webhookMockState.deliveryListNetworkError) {
      return HttpResponse.error();
    }
    const workspaceId = params.workspaceId as string;
    const url = new URL(request.url);
    const results = webhookMockState.deliveriesByWorkspace[workspaceId] ?? [];
    return HttpResponse.json(paginate(results, url));
  }),

  http.get(
    `${BASE}/api/v1/workspaces/:workspaceId/webhooks/deliveries/:deliveryId/`,
    async ({ params }) => {
      webhookMockState.deliveryDetailCallCount += 1;
      const workspaceId = params.workspaceId as string;
      const deliveryId = params.deliveryId as string;
      const delivery = webhookMockState.deliveriesByWorkspace[workspaceId]?.find(
        (d) => d.delivery_id === deliveryId,
      );
      if (!delivery) {
        return HttpResponse.json(
          { error: { code: "not_found", message: "Webhook delivery not found." } },
          { status: 404 },
        );
      }
      return HttpResponse.json(delivery);
    },
  ),
];
