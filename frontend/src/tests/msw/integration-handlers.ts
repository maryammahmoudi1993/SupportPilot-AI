/**
 * Request-level mocks for the integrations domain (Phase 22 Chunk 1),
 * mirroring the real backend contract (backend/integrations/views.py,
 * integrations/selectors.py, integrations/serializers.py): workspace-scoped
 * storage, no filter/search/ordering support (list/detail only — see
 * features/integrations/api.ts's schema-gap note), DRF
 * `PageNumberPagination`'s `{count,next,previous,results}` envelope, and the
 * real 404 tenant-hiding contract for both a nonexistent and a foreign-
 * workspace connection ID.
 */
import { HttpResponse, http } from "msw";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface IntegrationConnectionFixture {
  id: string;
  provider: "stripe" | "google_calendar" | "email" | "demo_commerce";
  display_name: string;
  status: "active" | "disabled" | "invalid_credentials" | "degraded";
  environment: "test" | "live";
  configuration: unknown;
  credentials_configured: boolean;
  credential_version: number;
  capabilities: string[];
  last_checked_at: string | null;
  last_success_at: string | null;
  last_error_code: string;
  created_at: string;
  updated_at: string;
}

const CAPABILITIES_BY_PROVIDER: Record<IntegrationConnectionFixture["provider"], string[]> = {
  stripe: ["payment_lookup", "refund"],
  google_calendar: ["calendar_availability", "calendar_booking"],
  email: ["notification_send"],
  demo_commerce: ["order_lookup", "shipment_lookup"],
};

export function makeIntegrationConnectionFixture(
  overrides: Partial<IntegrationConnectionFixture> & {
    id: string;
    provider: IntegrationConnectionFixture["provider"];
  },
): IntegrationConnectionFixture {
  const provider = overrides.provider;
  return {
    display_name: "",
    status: "active",
    environment: "test",
    configuration: {},
    credentials_configured: true,
    credential_version: 1,
    capabilities: CAPABILITIES_BY_PROVIDER[provider],
    last_checked_at: "2026-01-01T00:00:00Z",
    last_success_at: "2026-01-01T00:00:00Z",
    last_error_code: "",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export const integrationMockState = {
  connectionsByWorkspace: {} as Record<string, IntegrationConnectionFixture[]>,
  connectionListNetworkError: false,
  /** Phase 22 Chunk 3: a single mutation-error scenario, applied by every mutation handler below when set. */
  mutationError: null as { code: string; message: string; status: number } | null,
};

export function seedIntegrationConnections(
  workspaceId: string,
  connections: IntegrationConnectionFixture[],
): void {
  integrationMockState.connectionsByWorkspace[workspaceId] = connections;
}

export function resetIntegrationMockState(): void {
  integrationMockState.connectionsByWorkspace = {};
  integrationMockState.connectionListNetworkError = false;
  integrationMockState.mutationError = null;
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

export const integrationHandlers = [
  http.get(`${BASE}/api/v1/workspaces/:workspaceId/integrations/`, async ({ request, params }) => {
    if (integrationMockState.connectionListNetworkError) {
      return HttpResponse.error();
    }
    const workspaceId = params.workspaceId as string;
    const url = new URL(request.url);
    const results = integrationMockState.connectionsByWorkspace[workspaceId] ?? [];
    return HttpResponse.json(paginate(results, url));
  }),

  http.get(
    `${BASE}/api/v1/workspaces/:workspaceId/integrations/:connectionId/`,
    async ({ params }) => {
      const workspaceId = params.workspaceId as string;
      const connectionId = params.connectionId as string;
      const connection = integrationMockState.connectionsByWorkspace[workspaceId]?.find(
        (c) => c.id === connectionId,
      );
      if (!connection) {
        return HttpResponse.json(
          { error: { code: "not_found", message: "Integration connection not found." } },
          { status: 404 },
        );
      }
      return HttpResponse.json(connection);
    },
  ),

  // --- Mutations (Phase 22 Chunk 3) -------------------------------------

  http.post(`${BASE}/api/v1/workspaces/:workspaceId/integrations/`, async ({ request, params }) => {
    if (integrationMockState.mutationError) {
      const { code, message, status } = integrationMockState.mutationError;
      return HttpResponse.json({ error: { code, message } }, { status });
    }
    const workspaceId = params.workspaceId as string;
    const body = (await request.json()) as {
      provider: IntegrationConnectionFixture["provider"];
      display_name?: string;
      environment: "test" | "live";
      configuration?: unknown;
    };
    const connection = makeIntegrationConnectionFixture({
      id: `conn-created-${Date.now()}`,
      provider: body.provider,
      display_name: body.display_name ?? "",
      environment: body.environment,
      configuration: body.configuration ?? {},
    });
    integrationMockState.connectionsByWorkspace[workspaceId] = [
      ...(integrationMockState.connectionsByWorkspace[workspaceId] ?? []),
      connection,
    ];
    return HttpResponse.json(connection, { status: 201 });
  }),

  http.patch(
    `${BASE}/api/v1/workspaces/:workspaceId/integrations/:connectionId/`,
    async ({ request, params }) => {
      if (integrationMockState.mutationError) {
        const { code, message, status } = integrationMockState.mutationError;
        return HttpResponse.json({ error: { code, message } }, { status });
      }
      const workspaceId = params.workspaceId as string;
      const connectionId = params.connectionId as string;
      const body = (await request.json()) as { display_name?: string; configuration?: unknown };
      const list = integrationMockState.connectionsByWorkspace[workspaceId] ?? [];
      const index = list.findIndex((c) => c.id === connectionId);
      if (index === -1) {
        return HttpResponse.json(
          { error: { code: "not_found", message: "Integration connection not found." } },
          { status: 404 },
        );
      }
      list[index] = {
        ...list[index],
        ...(body.display_name !== undefined ? { display_name: body.display_name } : {}),
        ...(body.configuration !== undefined ? { configuration: body.configuration } : {}),
        updated_at: "2026-01-02T00:00:00Z",
      };
      return HttpResponse.json(list[index]);
    },
  ),

  http.put(
    `${BASE}/api/v1/workspaces/:workspaceId/integrations/:connectionId/credentials/`,
    async ({ params }) => {
      if (integrationMockState.mutationError) {
        const { code, message, status } = integrationMockState.mutationError;
        return HttpResponse.json({ error: { code, message } }, { status });
      }
      const workspaceId = params.workspaceId as string;
      const connectionId = params.connectionId as string;
      const list = integrationMockState.connectionsByWorkspace[workspaceId] ?? [];
      const index = list.findIndex((c) => c.id === connectionId);
      if (index === -1) {
        return HttpResponse.json(
          { error: { code: "not_found", message: "Integration connection not found." } },
          { status: 404 },
        );
      }
      list[index] = {
        ...list[index],
        credentials_configured: true,
        credential_version: list[index].credential_version + 1,
        status: "active",
        updated_at: "2026-01-02T00:00:00Z",
      };
      return HttpResponse.json(list[index]);
    },
  ),

  http.patch(
    `${BASE}/api/v1/workspaces/:workspaceId/integrations/:connectionId/enabled/`,
    async ({ request, params }) => {
      if (integrationMockState.mutationError) {
        const { code, message, status } = integrationMockState.mutationError;
        return HttpResponse.json({ error: { code, message } }, { status });
      }
      const workspaceId = params.workspaceId as string;
      const connectionId = params.connectionId as string;
      const body = (await request.json()) as { enabled: boolean };
      const list = integrationMockState.connectionsByWorkspace[workspaceId] ?? [];
      const index = list.findIndex((c) => c.id === connectionId);
      if (index === -1) {
        return HttpResponse.json(
          { error: { code: "not_found", message: "Integration connection not found." } },
          { status: 404 },
        );
      }
      list[index] = {
        ...list[index],
        status: body.enabled ? "active" : "disabled",
        updated_at: "2026-01-02T00:00:00Z",
      };
      return HttpResponse.json(list[index]);
    },
  ),

  http.post(
    `${BASE}/api/v1/workspaces/:workspaceId/integrations/:connectionId/test/`,
    async ({ params }) => {
      if (integrationMockState.mutationError) {
        const { code, message, status } = integrationMockState.mutationError;
        return HttpResponse.json({ error: { code, message } }, { status });
      }
      const workspaceId = params.workspaceId as string;
      const connectionId = params.connectionId as string;
      const connection = integrationMockState.connectionsByWorkspace[workspaceId]?.find(
        (c) => c.id === connectionId,
      );
      if (!connection) {
        return HttpResponse.json(
          { error: { code: "not_found", message: "Integration connection not found." } },
          { status: 404 },
        );
      }
      return HttpResponse.json({ ok: true, status: connection.status, error_code: null });
    },
  ),
];
