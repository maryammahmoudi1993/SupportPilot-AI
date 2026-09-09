/**
 * Request-level mocks for the handoffs domain (read-only this chunk),
 * mirroring the real backend contract (tickets/views.py, tickets/selectors.py,
 * tickets/serializers.py): workspace-scoped storage, `status`/`conversation`
 * filtering, DRF `PageNumberPagination`'s `{count,next,previous,results}`
 * envelope.
 */
import { HttpResponse, http } from "msw";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface HandoffFixture {
  id: string;
  conversation_id: string;
  agent_run_id: string | null;
  ticket_id: string | null;
  status: "pending" | "assigned" | "resolved" | "cancelled";
  reason_code: string;
  safe_summary: string;
  assigned_to: { id: string; email: string; role: string } | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
}

export function makeHandoffFixture(
  overrides: Partial<HandoffFixture> & { id: string; conversation_id: string },
): HandoffFixture {
  return {
    agent_run_id: null,
    ticket_id: null,
    status: "pending",
    reason_code: "customer_requested",
    safe_summary: "Customer explicitly asked to speak with a human agent.",
    assigned_to: null,
    resolved_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export const handoffMockState = {
  handoffsByWorkspace: {} as Record<string, HandoffFixture[]>,
  listNetworkError: false,
};

export function seedHandoffs(workspaceId: string, handoffs: HandoffFixture[]): void {
  handoffMockState.handoffsByWorkspace[workspaceId] = handoffs;
}

export function resetHandoffMockState(): void {
  handoffMockState.handoffsByWorkspace = {};
  handoffMockState.listNetworkError = false;
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

export const handoffHandlers = [
  http.get(`${BASE}/api/v1/workspaces/:workspaceId/handoffs/`, async ({ request, params }) => {
    if (handoffMockState.listNetworkError) {
      return HttpResponse.error();
    }
    const workspaceId = params.workspaceId as string;
    const url = new URL(request.url);
    const status = url.searchParams.get("status");
    const conversation = url.searchParams.get("conversation");
    let results = handoffMockState.handoffsByWorkspace[workspaceId] ?? [];
    if (status) {
      results = results.filter((handoff) => handoff.status === status);
    }
    if (conversation) {
      results = results.filter((handoff) => handoff.conversation_id === conversation);
    }
    return HttpResponse.json(paginate(results, url));
  }),

  http.get(`${BASE}/api/v1/workspaces/:workspaceId/handoffs/:handoffId/`, async ({ params }) => {
    const workspaceId = params.workspaceId as string;
    const handoffId = params.handoffId as string;
    const handoff = handoffMockState.handoffsByWorkspace[workspaceId]?.find(
      (h) => h.id === handoffId,
    );
    if (!handoff) {
      return HttpResponse.json(
        { error: { code: "not_found", message: "Handoff not found." } },
        { status: 404 },
      );
    }
    return HttpResponse.json(handoff);
  }),
];
