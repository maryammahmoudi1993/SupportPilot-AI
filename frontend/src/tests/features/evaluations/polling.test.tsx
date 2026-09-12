import { act, screen } from "@testing-library/react";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EvaluationRunDetailPage } from "@/features/evaluations/components/evaluation-run-detail-page";
import {
  EVALUATION_RUN_POLL_INTERVAL_MS,
  pollWhileNonTerminalRun,
} from "@/features/evaluations/queries";
import { isTerminalEvaluationRunStatus } from "@/features/evaluations/types";
import { FIXTURE_USER, FIXTURE_WORKSPACE_ACME, mockState } from "@/tests/msw/handlers";
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

const RUN_1 = "11111111-1111-4111-8111-111111111111";
const DATASET_1 = "22222222-2222-4222-8222-222222222222";
const VERSION_1 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

function signIn() {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = [FIXTURE_WORKSPACE_ACME];
}

function setupNavigationMocks() {
  vi.mocked(useRouter).mockReturnValue({
    replace: vi.fn(),
  } as unknown as ReturnType<typeof useRouter>);
  vi.mocked(usePathname).mockReturnValue("/app/evaluations/run-1");
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams() as unknown as ReturnType<typeof useSearchParams>,
  );
}

describe("isTerminalEvaluationRunStatus / pollWhileNonTerminalRun (pure decision logic)", () => {
  it("classifies every real terminal status as terminal", () => {
    for (const status of ["succeeded", "partial", "failed", "cancelled"] as const) {
      expect(isTerminalEvaluationRunStatus(status)).toBe(true);
    }
  });

  it("classifies pending/running as non-terminal", () => {
    for (const status of ["pending", "running"] as const) {
      expect(isTerminalEvaluationRunStatus(status)).toBe(false);
    }
  });

  it("stops polling once the fetched run is terminal", () => {
    expect(pollWhileNonTerminalRun({ state: { data: makeQueryRun("succeeded") } })).toBe(false);
  });

  it("keeps polling at the fixed interval while the run is non-terminal", () => {
    expect(pollWhileNonTerminalRun({ state: { data: makeQueryRun("running") } })).toBe(
      EVALUATION_RUN_POLL_INTERVAL_MS,
    );
  });

  it("does not poll before any data has been fetched yet", () => {
    expect(pollWhileNonTerminalRun({ state: { data: undefined } })).toBe(false);
  });

  function makeQueryRun(status: string) {
    return { status } as never;
  }
});

describe("EvaluationRunDetailPage polling (integration)", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("keeps re-fetching a non-terminal run and stops once it turns terminal", async () => {
    signIn();
    setupNavigationMocks();
    seedEvaluationRuns(FIXTURE_WORKSPACE_ACME.id, [
      makeEvaluationRunFixture({
        id: RUN_1,
        dataset_id: DATASET_1,
        agent_version_id: VERSION_1,
        status: "running",
      }),
    ]);

    renderAuthenticated(<EvaluationRunDetailPage runId={RUN_1} />);
    expect(await screen.findByText("Running")).toBeInTheDocument();

    const callsAfterInitial = evaluationMockState.detailCallCount;
    expect(callsAfterInitial).toBe(1);

    seedEvaluationRuns(FIXTURE_WORKSPACE_ACME.id, [
      makeEvaluationRunFixture({
        id: RUN_1,
        dataset_id: DATASET_1,
        agent_version_id: VERSION_1,
        status: "succeeded",
      }),
    ]);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(EVALUATION_RUN_POLL_INTERVAL_MS + 100);
    });
    expect(await screen.findByText("Succeeded")).toBeInTheDocument();
    const callsAfterTerminal = evaluationMockState.detailCallCount;
    expect(callsAfterTerminal).toBe(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(EVALUATION_RUN_POLL_INTERVAL_MS * 3);
    });
    expect(evaluationMockState.detailCallCount).toBe(callsAfterTerminal);
  });
});
