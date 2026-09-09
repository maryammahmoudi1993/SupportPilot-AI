import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { approveApproval, fetchApprovalList, rejectApproval } from "@/features/approvals/api";
import { server } from "@/tests/msw/server";

const BASE = "http://localhost:8000";

describe("fetchApprovalList request shape", () => {
  it("sends status and never sends search/ordering", async () => {
    let capturedUrl: URL | null = null;
    server.use(
      http.get(`${BASE}/api/v1/workspaces/:workspaceId/approvals/`, ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
      }),
    );

    await fetchApprovalList("ws-1", { page: 1, status: "pending" });

    const params = (capturedUrl as unknown as URL).searchParams;
    expect(params.get("status")).toBe("pending");
    expect(params.has("search")).toBe(false);
    expect(params.has("ordering")).toBe(false);
  });

  it("omits the status param entirely for 'all'", async () => {
    let capturedUrl: URL | null = null;
    server.use(
      http.get(`${BASE}/api/v1/workspaces/:workspaceId/approvals/`, ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
      }),
    );

    await fetchApprovalList("ws-1", { page: 1, status: "all" });

    expect((capturedUrl as unknown as URL).searchParams.has("status")).toBe(false);
  });
});

describe("approveApproval / rejectApproval", () => {
  it("POSTs to the approve endpoint with only a comment body", async () => {
    let capturedBody: unknown = null;
    let capturedPath: string | null = null;
    server.use(
      http.post(
        `${BASE}/api/v1/workspaces/:workspaceId/approvals/:approvalId/approve/`,
        async ({ request }) => {
          capturedBody = await request.json();
          capturedPath = new URL(request.url).pathname;
          return HttpResponse.json({
            id: "appr-1",
            status: "approved",
            required_role: "admin",
            requested_by: null,
            summary: "x",
            safe_context: {},
            expires_at: "2026-01-01T01:00:00Z",
            created_at: "2026-01-01T00:00:00Z",
            resolved_at: "2026-01-01T00:05:00Z",
            decision: null,
          });
        },
      ),
    );

    await approveApproval("ws-1", "appr-1", "looks fine");

    expect(capturedPath).toBe("/api/v1/workspaces/ws-1/approvals/appr-1/approve/");
    expect(capturedBody).toEqual({ comment: "looks fine" });
  });

  it("POSTs to the reject endpoint with an empty comment by default", async () => {
    let capturedBody: unknown = null;
    server.use(
      http.post(
        `${BASE}/api/v1/workspaces/:workspaceId/approvals/:approvalId/reject/`,
        async ({ request }) => {
          capturedBody = await request.json();
          return HttpResponse.json({
            id: "appr-1",
            status: "rejected",
            required_role: "admin",
            requested_by: null,
            summary: "x",
            safe_context: {},
            expires_at: "2026-01-01T01:00:00Z",
            created_at: "2026-01-01T00:00:00Z",
            resolved_at: "2026-01-01T00:05:00Z",
            decision: null,
          });
        },
      ),
    );

    await rejectApproval("ws-1", "appr-1");

    expect(capturedBody).toEqual({ comment: "" });
  });
});
