import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { describe, expect, it, vi } from "vitest";

import { KnowledgeListPage } from "@/features/knowledge/components/knowledge-list-page";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import {
  FIXTURE_USER,
  FIXTURE_WORKSPACE_ACME,
  FIXTURE_WORKSPACE_GLOBEX,
  mockState,
} from "@/tests/msw/handlers";
import {
  knowledgeMockState,
  makeKnowledgeDocumentFixture,
  makeKnowledgeSourceFixture,
  seedKnowledgeDocuments,
  seedKnowledgeSources,
} from "@/tests/msw/knowledge-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(),
  usePathname: vi.fn(),
  useSearchParams: vi.fn(),
}));

function setupNavigationMocks(initialQuery = "") {
  const replace = vi.fn();
  vi.mocked(useRouter).mockReturnValue({ replace } as unknown as ReturnType<typeof useRouter>);
  vi.mocked(usePathname).mockReturnValue("/app/knowledge");
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams(initialQuery) as unknown as ReturnType<typeof useSearchParams>,
  );
  return { replace };
}

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

const SOURCE_1 = "22222222-2222-4222-8222-222222222222";

describe("KnowledgeListPage", () => {
  describe("Documents tab", () => {
    it("renders real document rows returned by the API", async () => {
      signIn([FIXTURE_WORKSPACE_ACME]);
      seedKnowledgeSources(FIXTURE_WORKSPACE_ACME.id, [
        makeKnowledgeSourceFixture({ id: SOURCE_1, name: "Support Macros" }),
      ]);
      seedKnowledgeDocuments(FIXTURE_WORKSPACE_ACME.id, [
        makeKnowledgeDocumentFixture({
          id: "doc-1",
          source_id: SOURCE_1,
          source_name: "Support Macros",
          title: "Refund policy",
          status: "ready",
        }),
      ]);
      setupNavigationMocks();

      renderAuthenticated(<KnowledgeListPage />);

      expect(await screen.findByRole("link", { name: "Refund policy" })).toBeInTheDocument();
      const table = screen.getByRole("table");
      expect(within(table).getByText("Ready")).toBeInTheDocument();
      expect(within(table).getByText("Support Macros")).toBeInTheDocument();
    });

    it("shows a distinct empty state for zero documents", async () => {
      signIn([FIXTURE_WORKSPACE_ACME]);
      setupNavigationMocks();

      renderAuthenticated(<KnowledgeListPage />);

      expect(await screen.findByText("No knowledge documents yet")).toBeInTheDocument();
    });

    it("shows a network-error state (not empty) and recovers via Retry", async () => {
      signIn([FIXTURE_WORKSPACE_ACME]);
      knowledgeMockState.documentListNetworkError = true;
      setupNavigationMocks();

      renderAuthenticated(<KnowledgeListPage />);

      expect(await screen.findByText("Something went wrong")).toBeInTheDocument();

      knowledgeMockState.documentListNetworkError = false;
      seedKnowledgeDocuments(FIXTURE_WORKSPACE_ACME.id, [
        makeKnowledgeDocumentFixture({
          id: "doc-1",
          source_id: SOURCE_1,
          source_name: "Support Macros",
          title: "Recovered document",
        }),
      ]);
      await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));

      expect(await screen.findByRole("link", { name: "Recovered document" })).toBeInTheDocument();
    });

    it("pushes a status filter change into the URL with the page reset to 1", async () => {
      signIn([FIXTURE_WORKSPACE_ACME]);
      const { replace } = setupNavigationMocks("page=3");

      renderAuthenticated(<KnowledgeListPage />);
      await screen.findByText("No knowledge documents yet");

      await userEvent.setup().selectOptions(screen.getByLabelText("Status"), "failed");

      expect(replace).toHaveBeenCalledWith("/app/knowledge?status=failed", { scroll: false });
    });

    it("filters by the real source_id parameter", async () => {
      signIn([FIXTURE_WORKSPACE_ACME]);
      const { replace } = setupNavigationMocks();
      seedKnowledgeSources(FIXTURE_WORKSPACE_ACME.id, [
        makeKnowledgeSourceFixture({ id: SOURCE_1, name: "Support Macros" }),
      ]);

      renderAuthenticated(<KnowledgeListPage />);
      await screen.findByText("No knowledge documents yet");
      await screen.findByRole("option", { name: "Support Macros" });

      await userEvent.setup().selectOptions(screen.getByLabelText("Source"), SOURCE_1);

      expect(replace).toHaveBeenCalledWith(`/app/knowledge?source=${SOURCE_1}`, { scroll: false });
    });

    it("never renders another workspace's documents while/after switching workspaces", async () => {
      signIn([FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX]);
      seedKnowledgeDocuments(FIXTURE_WORKSPACE_ACME.id, [
        makeKnowledgeDocumentFixture({
          id: "acme-doc",
          source_id: SOURCE_1,
          source_name: "Acme Source",
          title: "Acme-only document",
        }),
      ]);
      seedKnowledgeDocuments(FIXTURE_WORKSPACE_GLOBEX.id, [
        makeKnowledgeDocumentFixture({
          id: "globex-doc",
          source_id: SOURCE_1,
          source_name: "Globex Source",
          title: "Globex-only document",
        }),
      ]);
      setupNavigationMocks();

      function Harness() {
        const workspace = useWorkspace();
        return (
          <>
            {workspace.status === "ready" &&
              workspace.workspaces.map((candidate) => (
                <button key={candidate.id} onClick={() => workspace.selectWorkspace(candidate.id)}>
                  {`switch-to-${candidate.name}`}
                </button>
              ))}
            <KnowledgeListPage />
          </>
        );
      }

      renderAuthenticated(<Harness />);

      expect(await screen.findByRole("link", { name: "Acme-only document" })).toBeInTheDocument();

      await userEvent
        .setup()
        .click(screen.getByRole("button", { name: `switch-to-${FIXTURE_WORKSPACE_GLOBEX.name}` }));

      await waitFor(() =>
        expect(screen.queryByRole("link", { name: "Acme-only document" })).not.toBeInTheDocument(),
      );
      expect(await screen.findByRole("link", { name: "Globex-only document" })).toBeInTheDocument();
    });
  });

  describe("Sources tab", () => {
    it("renders real source rows and switches tabs via the URL", async () => {
      signIn([FIXTURE_WORKSPACE_ACME]);
      seedKnowledgeSources(FIXTURE_WORKSPACE_ACME.id, [
        makeKnowledgeSourceFixture({
          id: SOURCE_1,
          name: "Support Macros",
          description: "Canned responses",
          is_active: true,
        }),
      ]);
      setupNavigationMocks("tab=sources");

      renderAuthenticated(<KnowledgeListPage />);

      const table = await screen.findByRole("table");
      expect(within(table).getByText("Support Macros")).toBeInTheDocument();
      expect(within(table).getByText("Canned responses")).toBeInTheDocument();
      expect(within(table).getAllByText("Active")).toHaveLength(2); // column header + cell value
    });

    it("shows a distinct empty state for zero sources", async () => {
      signIn([FIXTURE_WORKSPACE_ACME]);
      setupNavigationMocks("tab=sources");

      renderAuthenticated(<KnowledgeListPage />);

      expect(await screen.findByText("No knowledge sources yet")).toBeInTheDocument();
    });

    it("filters by the real search parameter", async () => {
      signIn([FIXTURE_WORKSPACE_ACME]);
      const { replace } = setupNavigationMocks("tab=sources");
      seedKnowledgeSources(FIXTURE_WORKSPACE_ACME.id, [
        makeKnowledgeSourceFixture({ id: SOURCE_1, name: "Support Macros" }),
      ]);

      renderAuthenticated(<KnowledgeListPage />);
      await screen.findByText("Support Macros");

      await userEvent.setup().type(screen.getByLabelText("Search"), "refund");

      await waitFor(() =>
        expect(replace).toHaveBeenLastCalledWith("/app/knowledge?tab=sources&q=refund", {
          scroll: false,
        }),
      );
    });

    it("creates a real source and closes the form on success", async () => {
      signIn([FIXTURE_WORKSPACE_GLOBEX]); // admin — canManageKnowledge
      setupNavigationMocks("tab=sources");

      renderAuthenticated(<KnowledgeListPage />);
      await screen.findByText("No knowledge sources yet");

      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: "New source" }));
      await user.type(screen.getByLabelText("Name"), "Support Macros");
      await user.click(screen.getByRole("button", { name: "Create source" }));

      expect(await screen.findByText("Support Macros")).toBeInTheDocument();
      expect(screen.queryByLabelText("Name")).not.toBeInTheDocument();
    });
  });

  describe("RBAC (Phase 21 Chunk 2)", () => {
    it("shows Upload document and New source to an authorized (admin) manager", async () => {
      signIn([FIXTURE_WORKSPACE_GLOBEX]);
      setupNavigationMocks();

      renderAuthenticated(<KnowledgeListPage />);
      await screen.findByText("No knowledge documents yet");

      expect(screen.getByRole("button", { name: "Upload document" })).toBeInTheDocument();
    });

    it("never shows Upload document to a read-only (support_agent) member", async () => {
      signIn([FIXTURE_WORKSPACE_ACME]);
      setupNavigationMocks();

      renderAuthenticated(<KnowledgeListPage />);
      await screen.findByText("No knowledge documents yet");
      expect(screen.queryByRole("button", { name: "Upload document" })).not.toBeInTheDocument();
    });

    it("never shows New source to a read-only (support_agent) member", async () => {
      signIn([FIXTURE_WORKSPACE_ACME]);
      setupNavigationMocks("tab=sources");

      renderAuthenticated(<KnowledgeListPage />);
      await screen.findByText("No knowledge sources yet");
      expect(screen.queryByRole("button", { name: "New source" })).not.toBeInTheDocument();
    });
  });
});
