import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { describe, expect, it, vi } from "vitest";

import { EvaluationDatasetDetailPage } from "@/features/evaluations/components/evaluation-dataset-detail-page";
import {
  FIXTURE_USER,
  FIXTURE_WORKSPACE_ACME,
  FIXTURE_WORKSPACE_GLOBEX,
  mockState,
} from "@/tests/msw/handlers";
import {
  evaluationMockState,
  makeEvaluationDatasetFixture,
  seedAgentDefinitions,
  seedAgentVersions,
  seedEvaluationDatasets,
} from "@/tests/msw/evaluation-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(),
  usePathname: vi.fn(),
  useSearchParams: vi.fn(),
}));

const DATASET_ID = "22222222-2222-4222-8222-222222222222";
const AGENT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const VERSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";

function setupNavigationMocks() {
  const push = vi.fn();
  const replace = vi.fn();
  vi.mocked(useRouter).mockReturnValue({ push, replace } as unknown as ReturnType<
    typeof useRouter
  >);
  vi.mocked(usePathname).mockReturnValue(`/app/evaluations/datasets/${DATASET_ID}`);
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams() as unknown as ReturnType<typeof useSearchParams>,
  );
  return { push, replace };
}

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

/**
 * Phase 23 Chunk 3: "Start Run" is scoped to the dataset detail page (see
 * evaluation-dataset-detail-page.tsx `StartRunPanel`) — bounded to picking a
 * published agent version, since the dataset itself is fixed by page
 * context. Gated to `CanRunEvaluations` roles (owner/admin/support_manager),
 * same role set as `CanManageEvaluations` — the backend's own permission
 * class is the real authority regardless of what renders here.
 */
describe("Start Evaluation Run (Phase 23 Chunk 3)", () => {
  it("hides the Start Run entry point for a role without run permission (support_agent)", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]); // support_agent
    seedEvaluationDatasets(FIXTURE_WORKSPACE_ACME.id, [
      makeEvaluationDatasetFixture({ id: DATASET_ID, name: "Refund Suite" }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<EvaluationDatasetDetailPage datasetId={DATASET_ID} />);

    expect(await screen.findByRole("heading", { name: "Refund Suite" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start run" })).not.toBeInTheDocument();
  });

  it("shows the Start Run entry point for a role with run permission (admin) and starts a run against a published version", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]); // admin
    seedEvaluationDatasets(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeEvaluationDatasetFixture({ id: DATASET_ID, name: "Refund Suite" }),
    ]);
    seedAgentDefinitions(FIXTURE_WORKSPACE_GLOBEX.id, [
      { id: AGENT_ID, name: "Support Agent", status: "active" },
    ]);
    seedAgentVersions(AGENT_ID, [
      { id: "draft-version", version: 1, status: "draft" },
      { id: VERSION_ID, version: 2, status: "published" },
    ]);
    const { push } = setupNavigationMocks();

    renderAuthenticated(<EvaluationDatasetDetailPage datasetId={DATASET_ID} />);
    await screen.findByRole("heading", { name: "Refund Suite" });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Start run" }));
    await user.selectOptions(await screen.findByLabelText("Agent"), AGENT_ID);

    // Only the published version is offered — the draft one is filtered out.
    const versionSelect = await screen.findByLabelText("Published version");
    expect(screen.queryByText("v1")).not.toBeInTheDocument();
    await user.selectOptions(versionSelect, VERSION_ID);
    await user.click(screen.getByRole("button", { name: "Start run" }));

    await waitFor(() => expect(evaluationMockState.runCreateCallCount).toBe(1));
    expect(evaluationMockState.runsByWorkspace[FIXTURE_WORKSPACE_GLOBEX.id]?.[0]).toMatchObject({
      dataset_id: DATASET_ID,
      agent_version_id: VERSION_ID,
      status: "pending",
    });
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith(expect.stringMatching(/^\/app\/evaluations\/run-1/)),
    );
  });

  it("blocks a duplicate submit while the start-run request is pending (mutation retry: 0)", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedEvaluationDatasets(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeEvaluationDatasetFixture({ id: DATASET_ID, name: "Refund Suite" }),
    ]);
    seedAgentDefinitions(FIXTURE_WORKSPACE_GLOBEX.id, [
      { id: AGENT_ID, name: "Support Agent", status: "active" },
    ]);
    seedAgentVersions(AGENT_ID, [{ id: VERSION_ID, version: 1, status: "published" }]);
    evaluationMockState.runCreateDelayMs = 200;
    const { push } = setupNavigationMocks();

    renderAuthenticated(<EvaluationDatasetDetailPage datasetId={DATASET_ID} />);
    await screen.findByRole("heading", { name: "Refund Suite" });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Start run" }));
    await user.selectOptions(await screen.findByLabelText("Agent"), AGENT_ID);
    await user.selectOptions(await screen.findByLabelText("Published version"), VERSION_ID);

    const submitButton = screen.getByRole("button", { name: "Start run" });
    await user.click(submitButton);

    await waitFor(() => expect(submitButton).toBeDisabled());
    // Clicking again while pending must not fire a second request.
    await user.click(submitButton);
    await waitFor(() => expect(evaluationMockState.runCreateCallCount).toBe(1));

    // Let the delayed response actually resolve before the test ends —
    // otherwise its in-flight timer can resolve during a LATER test and
    // consume that test's `nextRunCreateError`/call-count expectations.
    await waitFor(() => expect(push).toHaveBeenCalled(), { timeout: 1000 });
  });

  it("shows the real server rejection (e.g. no active cases) rather than a fabricated success", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedEvaluationDatasets(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeEvaluationDatasetFixture({ id: DATASET_ID, name: "Refund Suite" }),
    ]);
    seedAgentDefinitions(FIXTURE_WORKSPACE_GLOBEX.id, [
      { id: AGENT_ID, name: "Support Agent", status: "active" },
    ]);
    seedAgentVersions(AGENT_ID, [{ id: VERSION_ID, version: 1, status: "published" }]);
    evaluationMockState.nextRunCreateError = {
      status: 400,
      code: "evaluation_dataset_no_active_cases",
      message: "The dataset has no active cases to run.",
    };
    setupNavigationMocks();

    renderAuthenticated(<EvaluationDatasetDetailPage datasetId={DATASET_ID} />);
    await screen.findByRole("heading", { name: "Refund Suite" });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Start run" }));
    await user.selectOptions(await screen.findByLabelText("Agent"), AGENT_ID);
    await user.selectOptions(await screen.findByLabelText("Published version"), VERSION_ID);
    await user.click(screen.getByRole("button", { name: "Start run" }));

    await waitFor(() => expect(evaluationMockState.runCreateCallCount).toBe(1));
    expect(await screen.findByText("The dataset has no active cases to run.")).toBeInTheDocument();
  });

  it("shows an honest message when the selected agent has no published version", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedEvaluationDatasets(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeEvaluationDatasetFixture({ id: DATASET_ID, name: "Refund Suite" }),
    ]);
    seedAgentDefinitions(FIXTURE_WORKSPACE_GLOBEX.id, [
      { id: AGENT_ID, name: "Support Agent", status: "active" },
    ]);
    seedAgentVersions(AGENT_ID, [{ id: "draft-only", version: 1, status: "draft" }]);
    setupNavigationMocks();

    renderAuthenticated(<EvaluationDatasetDetailPage datasetId={DATASET_ID} />);
    await screen.findByRole("heading", { name: "Refund Suite" });

    await userEvent.setup().click(screen.getByRole("button", { name: "Start run" }));
    await userEvent.setup().selectOptions(await screen.findByLabelText("Agent"), AGENT_ID);

    expect(await screen.findByText("No published version")).toBeInTheDocument();
  });
});
