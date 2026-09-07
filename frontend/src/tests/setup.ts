import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach } from "vitest";

import { __resetSessionForTests } from "@/lib/api/session";
import { __resetTokenStoreForTests } from "@/lib/api/token-store";
import { resetAuthMockState } from "@/tests/msw/handlers";
import { server } from "@/tests/msw/server";

// `globals: false` in vitest.config.ts means @testing-library/react's
// automatic afterEach cleanup never registers itself — do it explicitly so
// one test's rendered DOM doesn't leak into the next.
afterEach(() => {
  cleanup();
});

// MSW: fail on any request that doesn't match a registered handler, so a
// forgotten mock shows up as a loud test failure rather than a silent
// real-network attempt.
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// The access token, in-flight refresh promise, and mock auth server state
// are all module-level singletons — reset them before every test so one
// test's login/refresh state never leaks into the next.
beforeEach(() => {
  __resetTokenStoreForTests();
  __resetSessionForTests();
  resetAuthMockState();
});
