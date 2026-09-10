import "@testing-library/jest-dom/vitest";

import { File as NodeFile } from "node:buffer";

import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach } from "vitest";

import { __setTimeoutOverrideForTests } from "@/lib/api/request";
import { __resetSessionForTests } from "@/lib/api/session";
import { __resetTokenStoreForTests } from "@/lib/api/token-store";
import { resetAgentRunMockState } from "@/tests/msw/agent-run-handlers";
import { resetApprovalMockState } from "@/tests/msw/approval-handlers";
import { resetAuthMockState } from "@/tests/msw/handlers";
import { resetCustomerMockState } from "@/tests/msw/customer-handlers";
import { resetConversationMockState } from "@/tests/msw/conversation-handlers";
import { resetHandoffMockState } from "@/tests/msw/handoff-handlers";
import { resetIntegrationMockState } from "@/tests/msw/integration-handlers";
import { resetKnowledgeMockState } from "@/tests/msw/knowledge-handlers";
import { resetTicketMockState } from "@/tests/msw/ticket-handlers";
import { resetToolExecutionMockState } from "@/tests/msw/tool-execution-handlers";
import { server } from "@/tests/msw/server";

// jsdom's own `File` class and Node's real `fetch` (undici, used by MSW's
// interception — the actual network layer in this test environment) are
// two different classes from two different realms: a real upload request's
// `FormData` carrying a jsdom `File` fails undici's internal webidl
// `File`/`Blob` type check with an opaque assertion error the moment MSW
// tries to parse the multipart body (Phase 21 Chunk 2, discovered writing
// the Knowledge upload tests — a jsdom/undici interop gap, not a product
// bug). Replacing the global `File` with Node's own (`node:buffer`, the
// same class undici itself resolves to) unifies both sides: React
// components, `userEvent.upload`, and the real fetch/FormData/MSW path all
// see the identical constructor, so a real multipart upload test actually
// works end-to-end instead of only exercising the UI in isolation.
globalThis.File = NodeFile as unknown as typeof File;

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
// test's login/refresh state never leaks into the next. localStorage now
// carries the (non-secret) logout-pending marker (src/lib/api/logout-intent.ts)
// and must be cleared the same way.
beforeEach(() => {
  __resetTokenStoreForTests();
  __resetSessionForTests();
  __setTimeoutOverrideForTests(null);
  resetAuthMockState();
  resetCustomerMockState();
  resetConversationMockState();
  resetTicketMockState();
  resetAgentRunMockState();
  resetToolExecutionMockState();
  resetApprovalMockState();
  resetHandoffMockState();
  resetKnowledgeMockState();
  resetIntegrationMockState();
  localStorage.clear();
  sessionStorage.clear();
});
