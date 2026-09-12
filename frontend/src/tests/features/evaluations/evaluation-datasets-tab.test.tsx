import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { describe, expect, it, vi } from "vitest";

import { EvaluationsListPage } from "@/features/evaluations/components/evaluations-list-page";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import {
  FIXTURE_USER,
  FIXTURE_WORKSPACE_ACME,
  FIXTURE_WORKSPACE_GLOBEX,
  mockState,
} from "@/tests/msw/handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";
import {
  armDatasetCreateGate,
  evaluationMockState,
  makeEvaluationDatasetFixture,
  seedEvaluationDatasets,
} from "@/tests/msw/evaluation-handlers";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(),
  usePathname: vi.fn(),
  useSearchParams: vi.fn(),
}));

function setupNavigationMocks(initialQuery = "tab=datasets") {
  const replace = vi.fn();
  vi.mocked(useRouter).mockReturnValue({ replace } as unknown as ReturnType<typeof useRouter>);
  vi.mocked(usePathname).mockReturnValue("/app/evaluations");
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams(initialQuery) as unknown as ReturnType<typeof useSearchParams>,
  );
  return { replace };
}

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

describe("EvaluationDatasetsTab (via EvaluationsListPage)", () => {
  it("renders real dataset rows — no invented quality/coverage labels", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedEvaluationDatasets(FIXTURE_WORKSPACE_ACME.id, [
      makeEvaluationDatasetFixture({
        id: "dataset-1",
        name: "Refund Suite",
        description: "Refund flow regression cases",
        status: "active",
      }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<EvaluationsListPage />);

    expect(await screen.findByRole("link", { name: "Refund Suite" })).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByText("Active")).toBeInTheDocument();
    expect(within(table).getByText("Refund flow regression cases")).toBeInTheDocument();
    expect(screen.queryByText(/quality score/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/coverage/i)).not.toBeInTheDocument();
  });

  it("shows a distinct empty state for zero datasets", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    setupNavigationMocks();

    renderAuthenticated(<EvaluationsListPage />);

    expect(await screen.findByText("No evaluation datasets yet")).toBeInTheDocument();
  });

  it("shows a network-error state (not empty) and recovers via Retry", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    evaluationMockState.datasetListNetworkError = true;
    setupNavigationMocks();

    renderAuthenticated(<EvaluationsListPage />);

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
    expect(screen.queryByText("No evaluation datasets yet")).not.toBeInTheDocument();

    evaluationMockState.datasetListNetworkError = false;
    seedEvaluationDatasets(FIXTURE_WORKSPACE_ACME.id, [
      makeEvaluationDatasetFixture({ id: "dataset-1", name: "Refund Suite" }),
    ]);
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("link", { name: "Refund Suite" })).toBeInTheDocument();
  });

  it("filters by status and resets the page in the URL", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    const { replace } = setupNavigationMocks("tab=datasets&page=3");

    renderAuthenticated(<EvaluationsListPage />);
    await screen.findByText("No evaluation datasets yet");

    await userEvent.setup().selectOptions(screen.getByLabelText("Status"), "archived");

    expect(replace).toHaveBeenCalledWith("/app/evaluations?tab=datasets&status=archived", {
      scroll: false,
    });
  });

  it("paginates using the backend's next/previous contract", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedEvaluationDatasets(
      FIXTURE_WORKSPACE_ACME.id,
      Array.from({ length: 55 }, (_, index) =>
        makeEvaluationDatasetFixture({ id: `dataset-${index}`, name: `Dataset ${index}` }),
      ),
    );
    setupNavigationMocks();

    renderAuthenticated(<EvaluationsListPage />);

    const nextButton = await screen.findByRole("button", { name: "Next page" });
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    expect(nextButton).toBeEnabled();

    await userEvent.setup().click(nextButton);

    expect(evaluationMockState.datasetListCallCount).toBeGreaterThan(0);
  });

  it("hides dataset create controls for a role without manage permission (support_agent)", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]); // support_agent
    setupNavigationMocks();

    renderAuthenticated(<EvaluationsListPage />);
    await screen.findByText("No evaluation datasets yet");

    expect(screen.queryByRole("button", { name: "New dataset" })).not.toBeInTheDocument();
  });

  it("shows dataset create controls for a role with manage permission (admin) and creates a dataset", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]); // admin
    setupNavigationMocks();

    renderAuthenticated(<EvaluationsListPage />);
    await screen.findByText("No evaluation datasets yet");

    await userEvent.setup().click(screen.getByRole("button", { name: "New dataset" }));
    await userEvent.setup().type(screen.getByLabelText("Name"), "New Suite");
    await userEvent.setup().click(screen.getByRole("button", { name: "Create dataset" }));

    expect(await screen.findByRole("link", { name: "New Suite" })).toBeInTheDocument();
    expect(evaluationMockState.datasetCreateCallCount).toBe(1);
  });

  it("shows a validation/ambiguous-failure error on create and never blindly resubmits (retry: 0)", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]); // admin
    evaluationMockState.nextCreateDatasetError = {
      status: 400,
      code: "invalid",
      message: "A dataset with this name already exists.",
    };
    setupNavigationMocks();

    renderAuthenticated(<EvaluationsListPage />);
    await screen.findByText("No evaluation datasets yet");

    await userEvent.setup().click(screen.getByRole("button", { name: "New dataset" }));
    await userEvent.setup().type(screen.getByLabelText("Name"), "Refund Suite");
    await userEvent.setup().click(screen.getByRole("button", { name: "Create dataset" }));

    expect(
      await screen.findByText("A dataset with this name already exists."),
    ).toBeInTheDocument();
    expect(evaluationMockState.datasetCreateCallCount).toBe(1);
  });

  it("blocks a duplicate submit while a create mutation is pending", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]); // admin
    setupNavigationMocks();

    renderAuthenticated(<EvaluationsListPage />);
    await screen.findByText("No evaluation datasets yet");

    await userEvent.setup().click(screen.getByRole("button", { name: "New dataset" }));
    await userEvent.setup().type(screen.getByLabelText("Name"), "Once Suite");

    const submit = screen.getByRole("button", { name: "Create dataset" });
    const user = userEvent.setup();
    await user.click(submit);
    await user.click(submit);

    await waitFor(() => expect(evaluationMockState.datasetCreateCallCount).toBe(1));
  });

  it("never renders another workspace's evaluation datasets while/after switching workspaces", async () => {
    signIn([FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX]);
    seedEvaluationDatasets(FIXTURE_WORKSPACE_ACME.id, [
      makeEvaluationDatasetFixture({ id: "acme-dataset", name: "Acme Suite" }),
    ]);
    seedEvaluationDatasets(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeEvaluationDatasetFixture({ id: "globex-dataset", name: "Globex Suite" }),
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
          <EvaluationsListPage />
        </>
      );
    }

    renderAuthenticated(<Harness />);

    expect(await screen.findByRole("link", { name: "Acme Suite" })).toBeInTheDocument();

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: `switch-to-${FIXTURE_WORKSPACE_GLOBEX.name}` }));

    await waitFor(() => expect(screen.queryByText("Acme Suite")).not.toBeInTheDocument());
    expect(await screen.findByRole("link", { name: "Globex Suite" })).toBeInTheDocument();
  });

  describe("mutation isolation across a workspace switch (Phase 23 Chunk 2A)", () => {
    it("a dataset-create response that arrives after switching to workspace B never renders in B, and B's own state is untouched", async () => {
      // Workspace A = Globex (admin, can create); Workspace B = Acme (already has its own dataset).
      signIn([FIXTURE_WORKSPACE_GLOBEX, FIXTURE_WORKSPACE_ACME]);
      seedEvaluationDatasets(FIXTURE_WORKSPACE_ACME.id, [
        makeEvaluationDatasetFixture({ id: "acme-dataset", name: "Acme Suite" }),
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
            <EvaluationsListPage />
          </>
        );
      }

      renderAuthenticated(<Harness />);

      // Start in Workspace A (Globex), which has no datasets yet.
      await screen.findByText("No evaluation datasets yet");

      // Hold the create response open — deterministic, no sleeps.
      const release = armDatasetCreateGate();
      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: "New dataset" }));
      await user.type(screen.getByLabelText("Name"), "Late A Dataset");
      await user.click(screen.getByRole("button", { name: "Create dataset" }));

      // The request left the component (fired against A's URL) but is held by the gate.
      await waitFor(() => expect(evaluationMockState.datasetCreateCallCount).toBe(1));
      expect(screen.queryByText("Late A Dataset")).not.toBeInTheDocument();

      // Switch to Workspace B before the held response is released.
      await user.click(
        screen.getByRole("button", { name: `switch-to-${FIXTURE_WORKSPACE_ACME.name}` }),
      );
      expect(await screen.findByRole("link", { name: "Acme Suite" })).toBeInTheDocument();
      // B has no create controls visible (support_agent) — no leaked A create form either.
      expect(screen.queryByRole("button", { name: "New dataset" })).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Name")).not.toBeInTheDocument();

      // Now let A's held response resolve.
      release();
      await waitFor(() =>
        expect(
          evaluationMockState.datasetsByWorkspace[FIXTURE_WORKSPACE_GLOBEX.id]?.some(
            (dataset) => dataset.name === "Late A Dataset",
          ),
        ).toBe(true),
      );

      // B's rendered view is still exactly B's: no A entity ever appears, B's own
      // dataset is still the only one shown, and B was never asked to re-list.
      expect(screen.queryByText("Late A Dataset")).not.toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Acme Suite" })).toBeInTheDocument();
      const table = screen.getByRole("table");
      expect(within(table).queryAllByRole("link").map((link) => link.textContent)).toEqual([
        "Acme Suite",
      ]);
    });
  });
});
