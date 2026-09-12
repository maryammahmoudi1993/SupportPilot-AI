import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { describe, expect, it, vi } from "vitest";

import { EvaluationsListPage } from "@/features/evaluations/components/evaluations-list-page";
import {
  FIXTURE_USER,
  FIXTURE_WORKSPACE_ACME,
  FIXTURE_WORKSPACE_GLOBEX,
  mockState,
} from "@/tests/msw/handlers";
import {
  evaluationMockState,
  makeEvaluationRunFixture,
  seedEvaluationRuns,
} from "@/tests/msw/evaluation-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(),
  usePathname: vi.fn(),
  useSearchParams: vi.fn(),
}));

function setupNavigationMocks() {
  const replace = vi.fn();
  vi.mocked(useRouter).mockReturnValue({ replace } as unknown as ReturnType<typeof useRouter>);
  vi.mocked(usePathname).mockReturnValue("/app/evaluations");
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams() as unknown as ReturnType<typeof useSearchParams>,
  );
}

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

const DATASET_1 = "22222222-2222-4222-8222-222222222222";
const VERSION_1 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const VERSION_2 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";

/**
 * Phase 23 Chunk 3 compare: contract re-discovery found a REAL backend
 * compare endpoint (`POST .../evaluations/compare/`,
 * `EvaluationRunCompareView`/`services.compare_evaluation_runs`) — this
 * exercises the real server-computed response shape, never a fabricated
 * client-side diff.
 */
describe("Compare Runs (Phase 23 Chunk 3)", () => {
  it("hides the compare checkboxes/button for a role without run permission (support_agent)", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]); // support_agent
    seedEvaluationRuns(FIXTURE_WORKSPACE_ACME.id, [
      makeEvaluationRunFixture({ id: "run-1", dataset_id: DATASET_1, agent_version_id: VERSION_1 }),
      makeEvaluationRunFixture({ id: "run-2", dataset_id: DATASET_1, agent_version_id: VERSION_2 }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<EvaluationsListPage />);

    await screen.findByText("Run #run-1".slice(0, 12));
    expect(screen.queryByText(/Compare selected/)).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("bounds selection to exactly two runs, replacing the oldest on a third pick", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]); // admin
    seedEvaluationRuns(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeEvaluationRunFixture({ id: "run-1", dataset_id: DATASET_1, agent_version_id: VERSION_1 }),
      makeEvaluationRunFixture({ id: "run-2", dataset_id: DATASET_1, agent_version_id: VERSION_2 }),
      makeEvaluationRunFixture({ id: "run-3", dataset_id: DATASET_1, agent_version_id: VERSION_2 }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<EvaluationsListPage />);
    await screen.findByText(/Compare selected/);

    const checkboxes = screen.getAllByRole("checkbox");
    const user = userEvent.setup();
    await user.click(checkboxes[0]);
    await user.click(checkboxes[1]);
    expect(screen.getByText("Compare selected (2/2)")).toBeInTheDocument();

    await user.click(checkboxes[2]);
    expect(screen.getByText("Compare selected (2/2)")).toBeInTheDocument();
    expect(checkboxes[0]).not.toBeChecked();
    expect(checkboxes[1]).toBeChecked();
    expect(checkboxes[2]).toBeChecked();
  });

  it("compares two selected runs and renders the real server-computed metrics, deltas, and threshold verdicts", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedEvaluationRuns(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeEvaluationRunFixture({ id: "run-1", dataset_id: DATASET_1, agent_version_id: VERSION_1 }),
      makeEvaluationRunFixture({ id: "run-2", dataset_id: DATASET_1, agent_version_id: VERSION_2 }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<EvaluationsListPage />);
    await screen.findByText(/Compare selected/);

    const checkboxes = screen.getAllByRole("checkbox");
    const user = userEvent.setup();
    await user.click(checkboxes[0]);
    await user.click(checkboxes[1]);
    await user.click(screen.getByRole("button", { name: "Compare selected (2/2)" }));

    await waitFor(() => expect(evaluationMockState.compareCallCount).toBe(1));
    expect(await screen.findByText("Comparison result")).toBeInTheDocument();
    // Real backend fields only: the mocked response's real pass rates/deltas.
    expect(screen.getByText("50.0%")).toBeInTheDocument();
    expect(screen.getByText("100.0%")).toBeInTheDocument();
    expect(screen.getByText("+50.0pp")).toBeInTheDocument();
    expect(screen.getByText(/Passed threshold checks/)).toBeInTheDocument();
    // Never an invented "quality score" or "improvement" percentage label.
    expect(screen.queryByText(/quality score/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/% improvement/i)).not.toBeInTheDocument();
  });

  it("shows the real 400 rejection for incompatible runs, never a fabricated comparison", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedEvaluationRuns(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeEvaluationRunFixture({ id: "run-1", dataset_id: DATASET_1, agent_version_id: VERSION_1 }),
      makeEvaluationRunFixture({
        id: "run-2",
        dataset_id: "other-dataset",
        agent_version_id: VERSION_2,
      }),
    ]);
    evaluationMockState.nextCompareError = {
      status: 400,
      code: "evaluation_runs_not_comparable",
      message: "These runs are not comparable — they were evaluated over incompatible cases.",
    };
    setupNavigationMocks();

    renderAuthenticated(<EvaluationsListPage />);
    await screen.findByText(/Compare selected/);

    const checkboxes = screen.getAllByRole("checkbox");
    const user = userEvent.setup();
    await user.click(checkboxes[0]);
    await user.click(checkboxes[1]);
    await user.click(screen.getByRole("button", { name: "Compare selected (2/2)" }));

    expect(
      await screen.findByText(
        "These runs are not comparable — they were evaluated over incompatible cases.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Comparison result")).not.toBeInTheDocument();
  });

  it("clears the selection and any prior comparison result", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedEvaluationRuns(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeEvaluationRunFixture({ id: "run-1", dataset_id: DATASET_1, agent_version_id: VERSION_1 }),
      makeEvaluationRunFixture({ id: "run-2", dataset_id: DATASET_1, agent_version_id: VERSION_2 }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<EvaluationsListPage />);
    await screen.findByText(/Compare selected/);

    const checkboxes = screen.getAllByRole("checkbox");
    const user = userEvent.setup();
    await user.click(checkboxes[0]);
    await user.click(checkboxes[1]);
    await user.click(screen.getByRole("button", { name: "Compare selected (2/2)" }));
    await screen.findByText("Comparison result");

    await user.click(screen.getByRole("button", { name: "Clear selection" }));

    expect(screen.queryByText("Comparison result")).not.toBeInTheDocument();
    expect(screen.getByText("Compare selected (0/2)")).toBeInTheDocument();
  });
});
