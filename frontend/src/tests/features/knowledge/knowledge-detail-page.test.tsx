import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { KnowledgeDocumentDetailPage } from "@/features/knowledge/components/knowledge-detail-page";
import {
  FIXTURE_USER,
  FIXTURE_WORKSPACE_ACME,
  FIXTURE_WORKSPACE_GLOBEX,
  mockState,
} from "@/tests/msw/handlers";
import {
  makeKnowledgeDocumentFixture,
  seedKnowledgeDocuments,
} from "@/tests/msw/knowledge-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

const DOC_1 = "11111111-1111-4111-8111-111111111111";
const SOURCE_1 = "22222222-2222-4222-8222-222222222222";

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

describe("KnowledgeDocumentDetailPage", () => {
  it("renders real document fields", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedKnowledgeDocuments(FIXTURE_WORKSPACE_ACME.id, [
      makeKnowledgeDocumentFixture({
        id: DOC_1,
        source_id: SOURCE_1,
        source_name: "Support Macros",
        title: "Refund policy",
        original_filename: "refund-policy.txt",
        content_type: "text/plain",
        file_size: 2048,
        status: "ready",
        chunk_count: 5,
        extracted_char_count: 1200,
      }),
    ]);

    renderAuthenticated(<KnowledgeDocumentDetailPage documentId={DOC_1} />);

    expect(await screen.findByRole("heading", { name: "Refund policy" })).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Support Macros" })).toBeInTheDocument();
    expect(screen.getByText("refund-policy.txt")).toBeInTheDocument();
    expect(screen.getByText("text/plain")).toBeInTheDocument();
    expect(screen.getByText("2.0 KB")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("Settled")).toBeInTheDocument();
  });

  it("shows a safe error state and no processing-state guess for a failed document", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedKnowledgeDocuments(FIXTURE_WORKSPACE_ACME.id, [
      makeKnowledgeDocumentFixture({
        id: DOC_1,
        source_id: SOURCE_1,
        source_name: "Support Macros",
        title: "Broken upload",
        status: "failed",
        last_error_code: "knowledge_malformed_pdf",
        last_error_message_safe: "The PDF is malformed or unreadable.",
      }),
    ]);

    renderAuthenticated(<KnowledgeDocumentDetailPage documentId={DOC_1} />);

    expect(await screen.findByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("The PDF is malformed or unreadable.")).toBeInTheDocument();
    expect(screen.getByText("Settled")).toBeInTheDocument();
  });

  it("shows 'still in progress' rather than inventing a percentage for a non-terminal status", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedKnowledgeDocuments(FIXTURE_WORKSPACE_ACME.id, [
      makeKnowledgeDocumentFixture({
        id: DOC_1,
        source_id: SOURCE_1,
        source_name: "Support Macros",
        title: "Still processing",
        status: "processing",
        last_ingested_at: null,
      }),
    ]);

    renderAuthenticated(<KnowledgeDocumentDetailPage documentId={DOC_1} />);

    expect(await screen.findByText("Still in progress")).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it("renders HTML/script-looking metadata as inert text, never executed", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedKnowledgeDocuments(FIXTURE_WORKSPACE_ACME.id, [
      makeKnowledgeDocumentFixture({
        id: DOC_1,
        source_id: SOURCE_1,
        source_name: "Support Macros",
        title: "Injection-shaped metadata",
        metadata: { note: "<script>window.__xss_marker = true;</script>" },
      }),
    ]);

    renderAuthenticated(<KnowledgeDocumentDetailPage documentId={DOC_1} />);

    await screen.findByRole("heading", { name: "Injection-shaped metadata" });
    // Rendered as plain text inside a `<pre>` (StructuredPayload never uses
    // dangerouslySetInnerHTML) — present verbatim as text, never as a real
    // executed <script> element.
    expect(
      screen.getByText(/window\.__xss_marker = true;/, { selector: "pre" }),
    ).toBeInTheDocument();
    expect(
      Array.from(document.querySelectorAll("script")).some((el) =>
        el.textContent?.includes("__xss_marker"),
      ),
    ).toBe(false);
    expect((window as unknown as { __xss_marker?: boolean }).__xss_marker).not.toBe(true);
  });

  it("renders an unrecognized future status value safely instead of crashing", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedKnowledgeDocuments(FIXTURE_WORKSPACE_ACME.id, [
      makeKnowledgeDocumentFixture({
        id: DOC_1,
        source_id: SOURCE_1,
        source_name: "Support Macros",
        title: "Mystery status",
        status: "mystery_status" as never,
      }),
    ]);

    renderAuthenticated(<KnowledgeDocumentDetailPage documentId={DOC_1} />);

    expect(await screen.findByText("mystery_status")).toBeInTheDocument();
  });

  it("shows a safe not-found state for a confirmed 404", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);

    renderAuthenticated(
      <KnowledgeDocumentDetailPage documentId="00000000-0000-4000-8000-000000000000" />,
    );

    expect(await screen.findByText("Document not found")).toBeInTheDocument();
  });

  it("shows a safe not-found state for a malformed route ID — never crashes", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);

    renderAuthenticated(<KnowledgeDocumentDetailPage documentId="not-a-uuid" />);

    expect(await screen.findByText("Document not found")).toBeInTheDocument();
  });

  it("shows a safe not-found state for a document belonging to a different workspace — never leaked", async () => {
    signIn([FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX]);
    seedKnowledgeDocuments(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeKnowledgeDocumentFixture({
        id: DOC_1,
        source_id: SOURCE_1,
        source_name: "Globex Source",
        title: "Globex-only document",
      }),
    ]);
    // Active workspace defaults to Acme; the document above belongs to Globex.

    renderAuthenticated(<KnowledgeDocumentDetailPage documentId={DOC_1} />);

    expect(await screen.findByText("Document not found")).toBeInTheDocument();
    expect(screen.queryByText("Globex-only document")).not.toBeInTheDocument();
  });
});
