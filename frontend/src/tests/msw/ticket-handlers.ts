/**
 * Request-level mocks for the tickets domain, mirroring the real backend
 * contract (tickets/views.py, tickets/selectors.py, tickets/serializers.py):
 * workspace-scoped storage, status/priority/customer filtering, DRF
 * `PageNumberPagination`'s `{count,next,previous,results}` envelope, and the
 * `{error:{code,message}}` failure envelope. Same pattern as
 * conversation-handlers.ts.
 */
import { HttpResponse, http } from "msw";

import type { MembershipSummaryFixture } from "@/tests/msw/conversation-handlers";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface TicketFixture {
  id: string;
  customer_id: string;
  conversation_id: string | null;
  subject: string;
  description: string;
  status: string;
  priority: string;
  assigned_to: MembershipSummaryFixture | null;
  due_at: string | null;
  resolved_at: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export function makeTicketFixture(
  overrides: Partial<TicketFixture> & { id: string; customer_id: string },
): TicketFixture {
  return {
    conversation_id: null,
    subject: "",
    description: "",
    status: "open",
    priority: "normal",
    assigned_to: null,
    due_at: null,
    resolved_at: null,
    metadata: {},
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export const ticketMockState = {
  ticketsByWorkspace: {} as Record<string, TicketFixture[]>,
  /** Which workspace owns a given ticket ID — for the cross-workspace 404 check. */
  ticketWorkspace: {} as Record<string, string>,
  listNetworkError: false,
  detailNetworkError: false,
  listCallCount: 0,
};

export function seedTickets(workspaceId: string, tickets: TicketFixture[]): void {
  ticketMockState.ticketsByWorkspace[workspaceId] = tickets;
  for (const ticket of tickets) {
    ticketMockState.ticketWorkspace[ticket.id] = workspaceId;
  }
}

export function resetTicketMockState(): void {
  ticketMockState.ticketsByWorkspace = {};
  ticketMockState.ticketWorkspace = {};
  ticketMockState.listNetworkError = false;
  ticketMockState.detailNetworkError = false;
  ticketMockState.listCallCount = 0;
}

function notFound() {
  return HttpResponse.json(
    { error: { code: "not_found", message: "Ticket not found." } },
    { status: 404 },
  );
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

export const ticketHandlers = [
  http.get(`${BASE}/api/v1/workspaces/:workspaceId/tickets/`, async ({ request, params }) => {
    ticketMockState.listCallCount += 1;

    if (ticketMockState.listNetworkError) {
      return HttpResponse.error();
    }

    const workspaceId = params.workspaceId as string;
    const url = new URL(request.url);
    const status = url.searchParams.get("status");
    const priority = url.searchParams.get("priority");
    const customer = url.searchParams.get("customer");

    let results = ticketMockState.ticketsByWorkspace[workspaceId] ?? [];
    if (status) {
      results = results.filter((ticket) => ticket.status === status);
    }
    if (priority) {
      results = results.filter((ticket) => ticket.priority === priority);
    }
    if (customer) {
      results = results.filter((ticket) => ticket.customer_id === customer);
    }

    return HttpResponse.json(paginate(results, url));
  }),

  http.get(`${BASE}/api/v1/workspaces/:workspaceId/tickets/:ticketId/`, async ({ params }) => {
    if (ticketMockState.detailNetworkError) {
      return HttpResponse.error();
    }

    const workspaceId = params.workspaceId as string;
    const ticketId = params.ticketId as string;
    const ticket = (ticketMockState.ticketsByWorkspace[workspaceId] ?? []).find(
      (candidate) => candidate.id === ticketId,
    );
    if (!ticket) {
      return notFound();
    }
    return HttpResponse.json(ticket);
  }),
];
