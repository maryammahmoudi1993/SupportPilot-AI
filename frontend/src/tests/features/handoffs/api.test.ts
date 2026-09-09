import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { fetchHandoffList, fetchHandoffsForConversation } from "@/features/handoffs/api";
import { server } from "@/tests/msw/server";

const BASE = "http://localhost:8000";

describe("fetchHandoffList request shape", () => {
  it("sends status and never sends search/ordering", async () => {
    let capturedUrl: URL | null = null;
    server.use(
      http.get(`${BASE}/api/v1/workspaces/:workspaceId/handoffs/`, ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
      }),
    );

    await fetchHandoffList("ws-1", { page: 1, status: "pending" });

    const params = (capturedUrl as unknown as URL).searchParams;
    expect(params.get("status")).toBe("pending");
    expect(params.has("search")).toBe(false);
    expect(params.has("ordering")).toBe(false);
  });
});

describe("fetchHandoffsForConversation", () => {
  it("sends the real conversation filter and no status filter", async () => {
    let capturedUrl: URL | null = null;
    server.use(
      http.get(`${BASE}/api/v1/workspaces/:workspaceId/handoffs/`, ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
      }),
    );

    await fetchHandoffsForConversation("ws-1", "conv-1");

    const params = (capturedUrl as unknown as URL).searchParams;
    expect(params.get("conversation")).toBe("conv-1");
    expect(params.has("status")).toBe(false);
  });
});
