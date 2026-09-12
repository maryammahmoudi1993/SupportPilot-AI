import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { describe, expect, it, vi } from "vitest";

import { EvaluationRunDetailPage } from "@/features/evaluations/components/evaluation-run-detail-page";
import {
  FIXTURE_USER,
  FIXTURE_WORKSPACE_ACME,
  FIXTURE_WORKSPACE_GLOBEX,
  mockState,
} from "@/tests/msw/handlers";
import {
  evaluationMockState,
  makeEvaluationResultFixture,
  makeEvaluationRunFixture,
  seedEvaluationResults,
  seedEvaluationRuns,
} from "@/tests/msw/evaluation-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(),
  usePathname: vi.fn(),
  useSearchParams: vi.fn(),
}));

const RUN_1 = "11111111-1111-4111-8111-111111111111";
const DATASET_1 = "33333333-3333-4333-8333-333333333333";
const VERSION_1 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

function setupNavigationMocks() {
  const replace = vi.fn();
  vi.mocked(useRouter).mockReturnValue({ replace } as unknown as ReturnType<typeof useRouter>);
  vi.mocked(usePathname).mockReturnValue("/app/evaluations/run-1");
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams() as unknown as ReturnType<typeof useSearchParams>,
  );
}

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

describe("Cancel Run (Phase 23 Chunk 3)", () => {
  it("hides the cancel control for a role without run permission (support_agent)", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]); // support_agent
    seedEvaluationRuns(FIXTURE_WORKSPACE_ACME.id, [
      makeEvaluationRunFixture({
        id: RUN_1,
        dataset_id: DATASET_1,
        agent_version_id: VERSION_1,
        status: "running",
      }),
    ]);
    seedEvaluationResults(RUN_1, []);
    setupNavigationMocks();

    renderAuthenticated(<EvaluationRunDetailPage runId={RUN_1} />);

    await screen.findByRole("heading", { name: `Run #${RUN_1.slice(0, 8)}` });
    expect(screen.queryByRole("button", { name: "Cancel run" })).not.toBeInTheDocument();
  });

  it("does not offer cancel for an already-terminal run", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]); // admin
    seedEvaluationRuns(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeEvaluationRunFixture({
        id: RUN_1,
        dataset_id: DATASET_1,
        agent_version_id: VERSION_1,
        status: "succeeded",
      }),
    ]);
    seedEvaluationResults(RUN_1, []);
    setupNavigationMocks();

    renderAuthenticated(<EvaluationRunDetailPage runId={RUN_1} />);

    await screen.findByRole("heading", { name: `Run #${RUN_1.slice(0, 8)}` });
    expect(screen.queryByRole("button", { name: "Cancel run" })).not.toBeInTheDocument();
  });

  it("requires confirmation, then cancels a non-terminal run and reflects the real new status", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedEvaluationRuns(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeEvaluationRunFixture({
        id: RUN_1,
        dataset_id: DATASET_1,
        agent_version_id: VERSION_1,
        status: "running",
      }),
    ]);
    seedEvaluationResults(RUN_1, []);
    setupNavigationMocks();

    renderAuthenticated(<EvaluationRunDetailPage runId={RUN_1} />);
    await screen.findByRole("heading", { name: `Run #${RUN_1.slice(0, 8)}` });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Cancel run" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^cancel run$/i }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(await screen.findByText("Evaluation run cancelled.")).toBeInTheDocument();
    expect(evaluationMockState.runCancelCallCount).toBe(1);
    // Cancel button disappears once the run's real status is terminal.
    expect(screen.queryByRole("button", { name: "Cancel run" })).not.toBeInTheDocument();
  });

  it("blocks a duplicate cancel submit while pending (mutation retry: 0)", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedEvaluationRuns(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeEvaluationRunFixture({
        id: RUN_1,
        dataset_id: DATASET_1,
        agent_version_id: VERSION_1,
        status: "running",
      }),
    ]);
    seedEvaluationResults(RUN_1, []);
    evaluationMockState.cancelDelayMs = 200;
    setupNavigationMocks();

    renderAuthenticated(<EvaluationRunDetailPage runId={RUN_1} />);
    await screen.findByRole("heading", { name: `Run #${RUN_1.slice(0, 8)}` });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Cancel run" }));
    const dialog = await screen.findByRole("dialog");
    const confirmButton = within(dialog).getByRole("button", { name: /^cancel run$/i });
    await user.click(confirmButton);

    await waitFor(() => expect(confirmButton).toBeDisabled());
    await waitFor(() => expect(evaluationMockState.runCancelCallCount).toBe(1));
    // Let the delayed response resolve before the test ends.
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument(), {
      timeout: 1000,
    });
  });

  it("shows the real 409 rejection when cancelling an already-terminal run, never a fabricated success", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedEvaluationRuns(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeEvaluationRunFixture({
        id: RUN_1,
        dataset_id: DATASET_1,
        agent_version_id: VERSION_1,
        status: "running",
      }),
    ]);
    seedEvaluationResults(RUN_1, []);
    evaluationMockState.nextCancelError = {
      status: 409,
      code: "evaluation_run_not_cancellable",
      message: "This evaluation run can no longer be cancelled.",
    };
    setupNavigationMocks();

    renderAuthenticated(<EvaluationRunDetailPage runId={RUN_1} />);
    await screen.findByRole("heading", { name: `Run #${RUN_1.slice(0, 8)}` });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Cancel run" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^cancel run$/i }));

    expect(
      await screen.findByText("This evaluation run can no longer be cancelled."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Evaluation run cancelled.")).not.toBeInTheDocument();
  });
});

describe("Replay Result (Phase 23 Chunk 3)", () => {
  it("hides the replay control for a role without run permission (support_agent)", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedEvaluationRuns(FIXTURE_WORKSPACE_ACME.id, [
      makeEvaluationRunFixture({ id: RUN_1, dataset_id: DATASET_1, agent_version_id: VERSION_1 }),
    ]);
    seedEvaluationResults(RUN_1, [
      makeEvaluationResultFixture({ id: "result-1", case_key: "refund-flow", status: "succeeded" }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<EvaluationRunDetailPage runId={RUN_1} />);
    await screen.findByText("refund-flow");
    expect(screen.queryByRole("button", { name: "Replay" })).not.toBeInTheDocument();
  });

  it("does not offer replay for a non-terminal result", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedEvaluationRuns(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeEvaluationRunFixture({
        id: RUN_1,
        dataset_id: DATASET_1,
        agent_version_id: VERSION_1,
        status: "running",
      }),
    ]);
    seedEvaluationResults(RUN_1, [
      makeEvaluationResultFixture({
        id: "result-1",
        case_key: "in-flight-case",
        status: "running",
        passed: null,
      }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<EvaluationRunDetailPage runId={RUN_1} />);
    await screen.findByText("in-flight-case");
    expect(screen.queryByRole("button", { name: "Replay" })).not.toBeInTheDocument();
  });

  it("replays a terminal result and shows the real queued confirmation", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedEvaluationRuns(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeEvaluationRunFixture({ id: RUN_1, dataset_id: DATASET_1, agent_version_id: VERSION_1 }),
    ]);
    seedEvaluationResults(RUN_1, [
      makeEvaluationResultFixture({ id: "result-1", case_key: "refund-flow", status: "succeeded" }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<EvaluationRunDetailPage runId={RUN_1} />);
    await screen.findByText("refund-flow");

    await userEvent.setup().click(screen.getByRole("button", { name: "Replay" }));

    expect(await screen.findByText("Replay queued as a new result.")).toBeInTheDocument();
    expect(evaluationMockState.replayCallCount).toBe(1);
  });

  it("blocks a duplicate replay submit while pending (mutation retry: 0)", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedEvaluationRuns(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeEvaluationRunFixture({ id: RUN_1, dataset_id: DATASET_1, agent_version_id: VERSION_1 }),
    ]);
    seedEvaluationResults(RUN_1, [
      makeEvaluationResultFixture({ id: "result-1", case_key: "refund-flow", status: "succeeded" }),
    ]);
    evaluationMockState.replayDelayMs = 200;
    setupNavigationMocks();

    renderAuthenticated(<EvaluationRunDetailPage runId={RUN_1} />);
    await screen.findByText("refund-flow");

    const user = userEvent.setup();
    const replayButton = screen.getByRole("button", { name: "Replay" });
    await user.click(replayButton);

    await waitFor(() => expect(replayButton).toBeDisabled());
    await user.click(replayButton);
    await waitFor(() => expect(evaluationMockState.replayCallCount).toBe(1));
    await waitFor(
      () => expect(screen.getByText("Replay queued as a new result.")).toBeInTheDocument(),
      {
        timeout: 1000,
      },
    );
  });

  it("shows the real 409 rejection when replay is not supported, never a fabricated success", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedEvaluationRuns(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeEvaluationRunFixture({ id: RUN_1, dataset_id: DATASET_1, agent_version_id: VERSION_1 }),
    ]);
    seedEvaluationResults(RUN_1, [
      makeEvaluationResultFixture({ id: "result-1", case_key: "refund-flow", status: "succeeded" }),
    ]);
    evaluationMockState.nextReplayError = {
      status: 409,
      code: "evaluation_result_not_replayable",
      message: "This result is not in a state that supports replay.",
    };
    setupNavigationMocks();

    renderAuthenticated(<EvaluationRunDetailPage runId={RUN_1} />);
    await screen.findByText("refund-flow");

    await userEvent.setup().click(screen.getByRole("button", { name: "Replay" }));

    expect(
      await screen.findByText("This result is not in a state that supports replay."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Replay queued as a new result.")).not.toBeInTheDocument();
  });
});
