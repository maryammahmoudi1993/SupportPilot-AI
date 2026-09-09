import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { fetchToolCatalog, fetchToolExecutionsForRun } from "@/features/tool-executions/api";
import { server } from "@/tests/msw/server";

const BASE = "http://localhost:8000";

describe("fetchToolExecutionsForRun request shape", () => {
  it("sends agent_run_id and never sends search/ordering", async () => {
    let capturedUrl: URL | null = null;
    server.use(
      http.get(`${BASE}/api/v1/workspaces/:workspaceId/tools/tool-executions/`, ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
      }),
    );

    await fetchToolExecutionsForRun("ws-1", "run-1");

    const params = (capturedUrl as unknown as URL).searchParams;
    expect(params.get("agent_run_id")).toBe("run-1");
    expect(params.has("search")).toBe(false);
    expect(params.has("ordering")).toBe(false);
  });
});

describe("fetchToolCatalog", () => {
  it("fetches the workspace's tool catalog with no filters", async () => {
    let capturedUrl: URL | null = null;
    server.use(
      http.get(`${BASE}/api/v1/workspaces/:workspaceId/tools/`, ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
      }),
    );

    await fetchToolCatalog("ws-1");

    expect((capturedUrl as unknown as URL).pathname).toBe("/api/v1/workspaces/ws-1/tools/");
  });
});
