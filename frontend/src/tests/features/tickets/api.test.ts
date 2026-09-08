import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { fetchTicketDetail, fetchTicketList } from "@/features/tickets/api";
import { server } from "@/tests/msw/server";

const BASE = "http://localhost:8000";

describe("fetchTicketList request shape", () => {
  it("omits page/status/priority/customer from the query string for default params", async () => {
    let capturedUrl: URL | null = null;
    server.use(
      http.get(`${BASE}/api/v1/workspaces/:workspaceId/tickets/`, ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
      }),
    );

    await fetchTicketList("ws-1", { page: 1, status: "all", priority: "all", customerId: null });

    const params = (capturedUrl as unknown as URL).searchParams;
    expect(params.has("page")).toBe(false);
    expect(params.has("status")).toBe(false);
    expect(params.has("priority")).toBe(false);
    expect(params.has("customer")).toBe(false);
    expect(params.has("search")).toBe(false);
    expect(params.has("ordering")).toBe(false);
  });

  it("sends page/status/priority/customer for non-default params", async () => {
    let capturedUrl: URL | null = null;
    server.use(
      http.get(`${BASE}/api/v1/workspaces/:workspaceId/tickets/`, ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
      }),
    );

    const customerId = "11111111-1111-4111-8111-111111111111";
    await fetchTicketList("ws-1", { page: 2, status: "open", priority: "urgent", customerId });

    const params = (capturedUrl as unknown as URL).searchParams;
    expect(params.get("page")).toBe("2");
    expect(params.get("status")).toBe("open");
    expect(params.get("priority")).toBe("urgent");
    expect(params.get("customer")).toBe(customerId);
  });
});

describe("fetchTicketDetail", () => {
  it("throws a not_found ApiError for a 404 response", async () => {
    server.use(
      http.get(`${BASE}/api/v1/workspaces/:workspaceId/tickets/:ticketId/`, () =>
        HttpResponse.json(
          { error: { code: "not_found", message: "Ticket not found." } },
          { status: 404 },
        ),
      ),
    );

    await expect(fetchTicketDetail("ws-1", "tick-1")).rejects.toMatchObject({ code: "not_found" });
  });
});
