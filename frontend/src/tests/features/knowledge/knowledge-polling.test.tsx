import { act, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { KnowledgeDocumentDetailPage } from "@/features/knowledge/components/knowledge-detail-page";
import {
  KNOWLEDGE_DOCUMENT_POLL_INTERVAL_MS,
  pollWhileDocumentNonTerminal,
} from "@/features/knowledge/queries";
import { isTerminalDocumentStatus } from "@/features/knowledge/types";
import { FIXTURE_USER, FIXTURE_WORKSPACE_ACME, mockState } from "@/tests/msw/handlers";
import {
  knowledgeMockState,
  makeKnowledgeDocumentFixture,
  seedKnowledgeDocuments,
} from "@/tests/msw/knowledge-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

const DOC_1 = "11111111-1111-4111-8111-111111111111";
const SOURCE_1 = "22222222-2222-4222-8222-222222222222";

function signIn() {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = [FIXTURE_WORKSPACE_ACME];
}

describe("isTerminalDocumentStatus / pollWhileDocumentNonTerminal (pure decision logic)", () => {
  it("classifies ready/failed as terminal", () => {
    expect(isTerminalDocumentStatus("ready")).toBe(true);
    expect(isTerminalDocumentStatus("failed")).toBe(true);
  });

  it("classifies pending/queued/processing as non-terminal", () => {
    expect(isTerminalDocumentStatus("pending")).toBe(false);
    expect(isTerminalDocumentStatus("queued")).toBe(false);
    expect(isTerminalDocumentStatus("processing")).toBe(false);
  });

  it("stops polling once the fetched document is terminal", () => {
    expect(pollWhileDocumentNonTerminal({ state: { data: makeQueryDoc("ready") } })).toBe(false);
  });

  it("keeps polling at the fixed interval while the document is non-terminal", () => {
    expect(pollWhileDocumentNonTerminal({ state: { data: makeQueryDoc("processing") } })).toBe(
      KNOWLEDGE_DOCUMENT_POLL_INTERVAL_MS,
    );
  });

  it("does not poll before any data has been fetched yet", () => {
    expect(pollWhileDocumentNonTerminal({ state: { data: undefined } })).toBe(false);
  });

  function makeQueryDoc(status: string) {
    return { status } as never;
  }
});

describe("KnowledgeDocumentDetailPage polling (integration)", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("keeps re-fetching a non-terminal document and stops once it turns terminal", async () => {
    signIn();
    seedKnowledgeDocuments(FIXTURE_WORKSPACE_ACME.id, [
      makeKnowledgeDocumentFixture({
        id: DOC_1,
        source_id: SOURCE_1,
        source_name: "Support Macros",
        title: "Refund policy",
        status: "processing",
      }),
    ]);

    renderAuthenticated(<KnowledgeDocumentDetailPage documentId={DOC_1} />);
    expect(await screen.findByText("Processing")).toBeInTheDocument();

    const callsAfterInitial = knowledgeMockState.documentDetailCallCount;
    expect(callsAfterInitial).toBe(1);

    // Flip the backend to terminal, then let one more poll interval pass.
    seedKnowledgeDocuments(FIXTURE_WORKSPACE_ACME.id, [
      makeKnowledgeDocumentFixture({
        id: DOC_1,
        source_id: SOURCE_1,
        source_name: "Support Macros",
        title: "Refund policy",
        status: "ready",
      }),
    ]);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(KNOWLEDGE_DOCUMENT_POLL_INTERVAL_MS + 100);
    });
    expect(await screen.findByText("Ready")).toBeInTheDocument();
    const callsAfterTerminal = knowledgeMockState.documentDetailCallCount;
    expect(callsAfterTerminal).toBe(2);

    // Advancing well past another interval must not produce a further fetch —
    // the document is terminal, so polling has genuinely stopped.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(KNOWLEDGE_DOCUMENT_POLL_INTERVAL_MS * 3);
    });
    expect(knowledgeMockState.documentDetailCallCount).toBe(callsAfterTerminal);
  });
});
