import { afterEach, describe, expect, it } from "vitest";

import { apiClient } from "@/lib/api/client";
import { setAccessToken, __resetTokenStoreForTests } from "@/lib/api/token-store";

/**
 * Regression test: NEXT_PUBLIC_API_BASE_URL is an origin with no path
 * (see .env.example) and the generated OpenAPI paths (src/types/api.ts) are
 * already absolute (e.g. "/api/v1/auth/csrf/"). openapi-fetch joins baseUrl
 * + path directly with no de-duplication, so a base URL that itself included
 * "/api/v1" would double it into ".../api/v1/api/v1/...". This was an actual
 * Chunk 1 → Chunk 2 defect, caught while wiring the first real request.
 */
describe("apiClient URL construction", () => {
  afterEach(() => {
    __resetTokenStoreForTests();
  });

  it("does not double the /api/v1 prefix", async () => {
    let requestedUrl: string | null = null;
    const capture = {
      onRequest({ request }: { request: Request }) {
        requestedUrl = request.url;
        // Short-circuit with a Response so no real network call is made.
        return new Response(null, { status: 204 });
      },
    };
    apiClient.use(capture);
    try {
      await apiClient.GET("/api/v1/auth/csrf/");
    } finally {
      apiClient.eject(capture);
    }

    expect(requestedUrl).toBe(`${process.env.NEXT_PUBLIC_API_BASE_URL}/api/v1/auth/csrf/`);
  });

  it("attaches an Authorization header only when an access token is held", async () => {
    let sawHeader: string | null = null;
    const capture = {
      onRequest({ request }: { request: Request }) {
        sawHeader = request.headers.get("Authorization");
        return new Response(null, { status: 204 });
      },
    };
    apiClient.use(capture);
    try {
      await apiClient.GET("/api/v1/auth/me/");
      expect(sawHeader).toBeNull();

      setAccessToken("test-access-token");
      await apiClient.GET("/api/v1/auth/me/");
      expect(sawHeader).toBe("Bearer test-access-token");
    } finally {
      apiClient.eject(capture);
    }
  });

  it("never attaches an X-CSRFToken header to a safe (GET) request", async () => {
    document.cookie = "sp_csrftoken=test-csrf-token";
    let sawHeader: string | null = null;
    const capture = {
      onRequest({ request }: { request: Request }) {
        sawHeader = request.headers.get("X-CSRFToken");
        return new Response(null, { status: 204 });
      },
    };
    apiClient.use(capture);
    try {
      await apiClient.GET("/api/v1/auth/me/");
    } finally {
      apiClient.eject(capture);
      document.cookie = "sp_csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
    }

    expect(sawHeader).toBeNull();
  });
});
