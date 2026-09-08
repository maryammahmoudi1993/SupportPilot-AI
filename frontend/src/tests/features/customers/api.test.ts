import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { fetchCustomerDetail, fetchCustomerList } from "@/features/customers/api";
import { ApiError } from "@/lib/api/errors";
import { server } from "@/tests/msw/server";

const BASE = "http://localhost:8000";

describe("fetchCustomerList request shape", () => {
  it("omits page/search/is_active from the query string for default params", async () => {
    let capturedUrl: URL | null = null;
    server.use(
      http.get(`${BASE}/api/v1/workspaces/:workspaceId/customers/`, ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
      }),
    );

    await fetchCustomerList("ws-1", { page: 1, search: "", status: "all" });

    expect(capturedUrl).not.toBeNull();
    const params = (capturedUrl as unknown as URL).searchParams;
    expect(params.has("page")).toBe(false);
    expect(params.has("search")).toBe(false);
    expect(params.has("is_active")).toBe(false);
  });

  it("sends page, trimmed search, and is_active=true/false for non-default params", async () => {
    let capturedUrl: URL | null = null;
    server.use(
      http.get(`${BASE}/api/v1/workspaces/:workspaceId/customers/`, ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
      }),
    );

    await fetchCustomerList("ws-1", { page: 2, search: "  jane  ", status: "active" });

    const params = (capturedUrl as unknown as URL).searchParams;
    expect(params.get("page")).toBe("2");
    expect(params.get("search")).toBe("jane");
    expect(params.get("is_active")).toBe("true");
  });

  it("sends is_active=false for the 'inactive' filter", async () => {
    let capturedUrl: URL | null = null;
    server.use(
      http.get(`${BASE}/api/v1/workspaces/:workspaceId/customers/`, ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
      }),
    );

    await fetchCustomerList("ws-1", { page: 1, search: "", status: "inactive" });

    expect((capturedUrl as unknown as URL).searchParams.get("is_active")).toBe("false");
  });

  it("never sends the backend-ignored 'ordering' parameter", async () => {
    let capturedUrl: URL | null = null;
    server.use(
      http.get(`${BASE}/api/v1/workspaces/:workspaceId/customers/`, ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
      }),
    );

    await fetchCustomerList("ws-1", { page: 1, search: "", status: "all" });

    expect((capturedUrl as unknown as URL).searchParams.has("ordering")).toBe(false);
  });
});

describe("fetchCustomerDetail", () => {
  it("throws a not_found ApiError for a 404 response", async () => {
    server.use(
      http.get(`${BASE}/api/v1/workspaces/:workspaceId/customers/:customerId/`, () =>
        HttpResponse.json({ error: { code: "not_found", message: "Customer not found." } }, { status: 404 }),
      ),
    );

    await expect(fetchCustomerDetail("ws-1", "cust-1")).rejects.toMatchObject({
      code: "not_found",
    } satisfies Partial<ApiError>);
  });
});
