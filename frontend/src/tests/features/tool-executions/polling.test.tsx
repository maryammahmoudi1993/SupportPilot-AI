import { act, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "@/features/auth/auth-provider";
import { ToolExecutionList } from "@/features/tool-executions/components/tool-execution-list";
import { TOOL_EXECUTION_POLL_INTERVAL_MS } from "@/features/tool-executions/queries";
import { WorkspaceProvider } from "@/features/workspace/workspace-provider";
import { QueryProvider } from "@/lib/query/query-provider";
import { FIXTURE_USER, FIXTURE_WORKSPACE_ACME, mockState } from "@/tests/msw/handlers";
import {
  makeToolExecutionFixture,
  seedToolCatalog,
  seedToolExecutions,
  toolExecutionMockState,
} from "@/tests/msw/tool-execution-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

/**
 * A rerender that keeps the SAME `QueryClient` (and thus the same query
 * cache/polling subscriptions) — RTL's `rerender` replaces exactly the
 * element tree passed to `render()`, and `renderAuthenticated` wraps its
 * argument in fresh providers itself, so rerendering with a bare
 * `<ToolExecutionList .../>` would unmount those providers instead of
 * updating props within them.
 */
function wrapped(ui: ReactElement) {
  return (
    <AuthProvider>
      <QueryProvider>
        <WorkspaceProvider>{ui}</WorkspaceProvider>
      </QueryProvider>
    </AuthProvider>
  );
}

const RUN_1 = "11111111-1111-4111-8111-111111111111";
const TOOL_ECHO = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

function signIn() {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = [FIXTURE_WORKSPACE_ACME];
}

describe("ToolExecutionList polling", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("polls the run's tool-execution list — a single list request per interval, not one per execution — while the run is non-terminal, and stops once terminal", async () => {
    signIn();
    seedToolCatalog(FIXTURE_WORKSPACE_ACME.id, []);
    seedToolExecutions(FIXTURE_WORKSPACE_ACME.id, [
      makeToolExecutionFixture({
        id: "exec-1",
        agent_run_id: RUN_1,
        tool_definition_id: TOOL_ECHO,
        tool_key: "demo.echo",
        status: "running",
      }),
      makeToolExecutionFixture({
        id: "exec-2",
        agent_run_id: RUN_1,
        tool_definition_id: TOOL_ECHO,
        tool_key: "demo.add",
        status: "running",
      }),
    ]);

    const { rerender } = renderAuthenticated(
      <ToolExecutionList
        workspaceId={FIXTURE_WORKSPACE_ACME.id}
        runId={RUN_1}
        runStatus="running"
      />,
    );
    await screen.findByText("demo.echo");
    expect(toolExecutionMockState.listCallCount).toBe(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(TOOL_EXECUTION_POLL_INTERVAL_MS + 100);
    });
    // One additional list request for BOTH executions together — never 2
    // (one per execution).
    expect(toolExecutionMockState.listCallCount).toBe(2);

    rerender(
      wrapped(
        <ToolExecutionList
          workspaceId={FIXTURE_WORKSPACE_ACME.id}
          runId={RUN_1}
          runStatus="succeeded"
        />,
      ),
    );
    const callsAtTerminal = toolExecutionMockState.listCallCount;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(TOOL_EXECUTION_POLL_INTERVAL_MS * 3);
    });
    expect(toolExecutionMockState.listCallCount).toBe(callsAtTerminal);
  });

  it("never polls the tool catalog", async () => {
    signIn();
    seedToolCatalog(FIXTURE_WORKSPACE_ACME.id, []);
    seedToolExecutions(FIXTURE_WORKSPACE_ACME.id, []);

    renderAuthenticated(
      <ToolExecutionList
        workspaceId={FIXTURE_WORKSPACE_ACME.id}
        runId={RUN_1}
        runStatus="running"
      />,
    );
    await screen.findByText("No tool executions recorded for this run.");
    expect(toolExecutionMockState.catalogCallCount).toBe(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(TOOL_EXECUTION_POLL_INTERVAL_MS * 3);
    });
    expect(toolExecutionMockState.catalogCallCount).toBe(1);
  });
});
