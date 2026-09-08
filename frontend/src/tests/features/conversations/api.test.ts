import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { fetchConversationDetail, fetchConversationList, fetchMessageList } from "@/features/conversations/api";
import { server } from "@/tests/msw/server";

const BASE = "http://localhost:8000";

describe("fetchConversationList request shape", () => {
  it("omits page/status/channel/unassigned from the query string for default params", async () => {
    let capturedUrl: URL | null = null;
    server.use(
      http.get(`${BASE}/api/v1/workspaces/:workspaceId/conversations/`, ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
      }),
    );

    await fetchConversationList("ws-1", { page: 1, status: "all", channel: "all", assignment: "all" });

    const params = (capturedUrl as unknown as URL).searchParams;
    expect(params.has("page")).toBe(false);
    expect(params.has("status")).toBe(false);
    expect(params.has("channel")).toBe(false);
    expect(params.has("unassigned")).toBe(false);
    expect(params.has("search")).toBe(false);
    expect(params.has("ordering")).toBe(false);
  });

  it("sends page/status/channel/unassigned for non-default params", async () => {
    let capturedUrl: URL | null = null;
    server.use(
      http.get(`${BASE}/api/v1/workspaces/:workspaceId/conversations/`, ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
      }),
    );

    await fetchConversationList("ws-1", {
      page: 2,
      status: "open",
      channel: "email",
      assignment: "unassigned",
    });

    const params = (capturedUrl as unknown as URL).searchParams;
    expect(params.get("page")).toBe("2");
    expect(params.get("status")).toBe("open");
    expect(params.get("channel")).toBe("email");
    expect(params.get("unassigned")).toBe("true");
  });
});

describe("fetchConversationDetail", () => {
  it("throws a not_found ApiError for a 404 response", async () => {
    server.use(
      http.get(`${BASE}/api/v1/workspaces/:workspaceId/conversations/:conversationId/`, () =>
        HttpResponse.json(
          { error: { code: "not_found", message: "Conversation not found." } },
          { status: 404 },
        ),
      ),
    );

    await expect(fetchConversationDetail("ws-1", "conv-1")).rejects.toMatchObject({
      code: "not_found",
    });
  });
});

describe("fetchMessageList request shape", () => {
  it("never sends search/ordering — dead parameters on the real backend", async () => {
    let capturedUrl: URL | null = null;
    server.use(
      http.get(
        `${BASE}/api/v1/workspaces/:workspaceId/conversations/:conversationId/messages/`,
        ({ request }) => {
          capturedUrl = new URL(request.url);
          return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
        },
      ),
    );

    await fetchMessageList("ws-1", "conv-1", { page: 1 });

    const params = (capturedUrl as unknown as URL).searchParams;
    expect(params.has("search")).toBe(false);
    expect(params.has("ordering")).toBe(false);
    expect(params.has("page")).toBe(false);
  });
});
