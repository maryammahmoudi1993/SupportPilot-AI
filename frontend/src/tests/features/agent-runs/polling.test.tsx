import { act, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AgentRunDetailPage } from "@/features/agent-runs/components/agent-run-detail-page";
import { AGENT_RUN_POLL_INTERVAL_MS, pollWhileNonTerminal } from "@/features/agent-runs/queries";
import { isTerminalRunStatus } from "@/features/agent-runs/types";
import { FIXTURE_USER, FIXTURE_WORKSPACE_ACME, mockState } from "@/tests/msw/handlers";
import {
  agentRunMockState,
  makeAgentRunFixture,
  seedAgentRuns,
  seedAgentSteps,
} from "@/tests/msw/agent-run-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

const RUN_1 = "11111111-1111-4111-8111-111111111111";
const VERSION_1 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

function signIn() {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = [FIXTURE_WORKSPACE_ACME];
}

describe("isTerminalRunStatus / pollWhileNonTerminal (pure decision logic)", () => {
  it("classifies every real terminal status as terminal", () => {
    for (const status of [
      "succeeded",
      "failed",
      "cancelled",
      "budget_exceeded",
      "handed_off",
    ] as const) {
      expect(isTerminalRunStatus(status)).toBe(true);
    }
  });

  it("classifies pending/running/waiting_for_approval as non-terminal", () => {
    for (const status of ["pending", "running", "waiting_for_approval"] as const) {
      expect(isTerminalRunStatus(status)).toBe(false);
    }
  });

  it("stops polling once the fetched run is terminal", () => {
    expect(pollWhileNonTerminal({ state: { data: makeQueryRun("succeeded") } })).toBe(false);
  });

  it("keeps polling at the fixed interval while the run is non-terminal", () => {
    expect(pollWhileNonTerminal({ state: { data: makeQueryRun("running") } })).toBe(
      AGENT_RUN_POLL_INTERVAL_MS,
    );
  });

  it("does not poll before any data has been fetched yet", () => {
    expect(pollWhileNonTerminal({ state: { data: undefined } })).toBe(false);
  });

  function makeQueryRun(status: string) {
    return { status } as never;
  }
});

describe("AgentRunDetailPage polling (integration)", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("keeps re-fetching a non-terminal run and stops once it turns terminal", async () => {
    signIn();
    seedAgentRuns(FIXTURE_WORKSPACE_ACME.id, [
      makeAgentRunFixture({ id: RUN_1, agent_version_id: VERSION_1, status: "running" }),
    ]);
    seedAgentSteps(RUN_1, []);

    renderAuthenticated(<AgentRunDetailPage runId={RUN_1} />);
    expect(await screen.findByText("Running")).toBeInTheDocument();

    const callsAfterInitial = agentRunMockState.detailCallCount;
    expect(callsAfterInitial).toBe(1);

    // Flip the backend to terminal, then let one more poll interval pass.
    seedAgentRuns(FIXTURE_WORKSPACE_ACME.id, [
      makeAgentRunFixture({ id: RUN_1, agent_version_id: VERSION_1, status: "succeeded" }),
    ]);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(AGENT_RUN_POLL_INTERVAL_MS + 100);
    });
    expect(await screen.findByText("Succeeded")).toBeInTheDocument();
    const callsAfterTerminal = agentRunMockState.detailCallCount;
    expect(callsAfterTerminal).toBe(2);

    // Advancing well past another interval must not produce a further fetch —
    // the run is terminal, so polling has genuinely stopped, not merely slowed.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(AGENT_RUN_POLL_INTERVAL_MS * 3);
    });
    expect(agentRunMockState.detailCallCount).toBe(callsAfterTerminal);
  });
});
