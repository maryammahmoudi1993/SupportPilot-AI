import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ToolExecutionList } from "@/features/tool-executions/components/tool-execution-list";
import { FIXTURE_USER, FIXTURE_WORKSPACE_ACME, mockState } from "@/tests/msw/handlers";
import {
  makeToolDefinitionFixture,
  makeToolExecutionFixture,
  seedToolCatalog,
  seedToolExecutions,
  toolExecutionMockState,
} from "@/tests/msw/tool-execution-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

const RUN_1 = "11111111-1111-4111-8111-111111111111";
const TOOL_ECHO = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

function signIn() {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = [FIXTURE_WORKSPACE_ACME];
}

describe("ToolExecutionList", () => {
  it("shows a distinct empty state when the run has no tool executions", async () => {
    signIn();
    seedToolExecutions(FIXTURE_WORKSPACE_ACME.id, []);
    seedToolCatalog(FIXTURE_WORKSPACE_ACME.id, []);

    renderAuthenticated(
      <ToolExecutionList
        workspaceId={FIXTURE_WORKSPACE_ACME.id}
        runId={RUN_1}
        runStatus="succeeded"
      />,
    );

    expect(
      await screen.findByText("No tool executions recorded for this run."),
    ).toBeInTheDocument();
  });

  it("renders a successful execution with real fields, catalog risk/side-effect, and no approval note", async () => {
    signIn();
    seedToolCatalog(FIXTURE_WORKSPACE_ACME.id, [
      makeToolDefinitionFixture({
        id: TOOL_ECHO,
        key: "demo.echo",
        display_name: "Echo",
        risk_level: "read_only",
        side_effect_type: "none",
      }),
    ]);
    seedToolExecutions(FIXTURE_WORKSPACE_ACME.id, [
      makeToolExecutionFixture({
        id: "exec-1",
        agent_run_id: RUN_1,
        tool_definition_id: TOOL_ECHO,
        tool_key: "demo.echo",
        status: "succeeded",
        attempt_count: 1,
        arguments_redacted: { message: "hello" },
        result_redacted: { echoed: "hello" },
      }),
    ]);

    renderAuthenticated(
      <ToolExecutionList
        workspaceId={FIXTURE_WORKSPACE_ACME.id}
        runId={RUN_1}
        runStatus="succeeded"
      />,
    );

    expect(await screen.findByText("Echo")).toBeInTheDocument();
    expect(screen.getByText("Succeeded")).toBeInTheDocument();
    expect(screen.getByText("Read only")).toBeInTheDocument();
    expect(screen.getByText("No side effect")).toBeInTheDocument();
    expect(screen.queryByText(/approval/i)).not.toBeInTheDocument();
    expect(screen.getByText(/"echoed": "hello"/)).toBeInTheDocument();
  });

  it("renders a failed execution's safe error fields without a raw traceback", async () => {
    signIn();
    seedToolCatalog(FIXTURE_WORKSPACE_ACME.id, []);
    seedToolExecutions(FIXTURE_WORKSPACE_ACME.id, [
      makeToolExecutionFixture({
        id: "exec-1",
        agent_run_id: RUN_1,
        tool_definition_id: TOOL_ECHO,
        tool_key: "demo.flaky",
        status: "failed",
        error_code: "tool_execution_failed",
        error_message_safe: "The tool failed after its final attempt.",
        attempt_count: 4,
      }),
    ]);

    renderAuthenticated(
      <ToolExecutionList
        workspaceId={FIXTURE_WORKSPACE_ACME.id}
        runId={RUN_1}
        runStatus="failed"
      />,
    );

    expect(await screen.findByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("The tool failed after its final attempt.")).toBeInTheDocument();
    expect(screen.getByText("tool_execution_failed")).toBeInTheDocument();
    // Falls back to the tool_key when no catalog entry matched.
    expect(screen.getByText("demo.flaky")).toBeInTheDocument();
  });

  it("renders multiple attempts honestly as a count, not as if the tool only ran once", async () => {
    signIn();
    seedToolCatalog(FIXTURE_WORKSPACE_ACME.id, []);
    seedToolExecutions(FIXTURE_WORKSPACE_ACME.id, [
      makeToolExecutionFixture({
        id: "exec-1",
        agent_run_id: RUN_1,
        tool_definition_id: TOOL_ECHO,
        tool_key: "demo.flaky",
        status: "succeeded",
        attempt_count: 3,
      }),
    ]);

    renderAuthenticated(
      <ToolExecutionList
        workspaceId={FIXTURE_WORKSPACE_ACME.id}
        runId={RUN_1}
        runStatus="succeeded"
      />,
    );

    await screen.findByText("demo.flaky");
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("shows the real read-only approval context for a waiting_for_approval execution — no Approve/Reject buttons", async () => {
    signIn();
    seedToolCatalog(FIXTURE_WORKSPACE_ACME.id, []);
    seedToolExecutions(FIXTURE_WORKSPACE_ACME.id, [
      makeToolExecutionFixture({
        id: "exec-1",
        agent_run_id: RUN_1,
        tool_definition_id: TOOL_ECHO,
        tool_key: "demo.refund",
        status: "waiting_for_approval",
      }),
    ]);

    renderAuthenticated(
      <ToolExecutionList
        workspaceId={FIXTURE_WORKSPACE_ACME.id}
        runId={RUN_1}
        runStatus="waiting_for_approval"
      />,
    );

    expect(await screen.findByText("Waiting for approval")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /reject/i })).not.toBeInTheDocument();
  });

  it("shows a specific rejected/expired approval-terminated reason derived from error_code", async () => {
    signIn();
    seedToolCatalog(FIXTURE_WORKSPACE_ACME.id, []);
    seedToolExecutions(FIXTURE_WORKSPACE_ACME.id, [
      makeToolExecutionFixture({
        id: "exec-1",
        agent_run_id: RUN_1,
        tool_definition_id: TOOL_ECHO,
        tool_key: "demo.refund",
        status: "approval_terminated",
        error_code: "approval_rejected",
      }),
    ]);

    renderAuthenticated(
      <ToolExecutionList
        workspaceId={FIXTURE_WORKSPACE_ACME.id}
        runId={RUN_1}
        runStatus="failed"
      />,
    );

    expect(await screen.findByText("Approval rejected")).toBeInTheDocument();
  });

  it("renders a redacted argument exactly as sent, never reconstructing the secret", async () => {
    signIn();
    seedToolCatalog(FIXTURE_WORKSPACE_ACME.id, []);
    seedToolExecutions(FIXTURE_WORKSPACE_ACME.id, [
      makeToolExecutionFixture({
        id: "exec-1",
        agent_run_id: RUN_1,
        tool_definition_id: TOOL_ECHO,
        tool_key: "demo.echo",
        arguments_redacted: { api_key: "***REDACTED***", message: "fake-not-a-real-secret" },
      }),
    ]);

    renderAuthenticated(
      <ToolExecutionList
        workspaceId={FIXTURE_WORKSPACE_ACME.id}
        runId={RUN_1}
        runStatus="succeeded"
      />,
    );

    expect(await screen.findByText(/\*\*\*REDACTED\*\*\*/)).toBeInTheDocument();
  });

  it("preserves the exact order the backend returns, without re-sorting", async () => {
    signIn();
    seedToolCatalog(FIXTURE_WORKSPACE_ACME.id, []);
    // Identical timestamps — the backend's own tie-breaker (id, via
    // -created_at,-id) is what determines order; this asserts the frontend
    // renders the API's array order verbatim rather than re-deriving one.
    seedToolExecutions(FIXTURE_WORKSPACE_ACME.id, [
      makeToolExecutionFixture({
        id: "exec-second",
        agent_run_id: RUN_1,
        tool_definition_id: TOOL_ECHO,
        tool_key: "demo.add",
        created_at: "2026-01-01T00:00:00Z",
      }),
      makeToolExecutionFixture({
        id: "exec-first",
        agent_run_id: RUN_1,
        tool_definition_id: TOOL_ECHO,
        tool_key: "demo.echo",
        created_at: "2026-01-01T00:00:00Z",
      }),
    ]);

    renderAuthenticated(
      <ToolExecutionList
        workspaceId={FIXTURE_WORKSPACE_ACME.id}
        runId={RUN_1}
        runStatus="succeeded"
      />,
    );

    const list = await screen.findByRole("list", { name: "Tool executions" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(within(items[0]).getByText("demo.add")).toBeInTheDocument();
    expect(within(items[1]).getByText("demo.echo")).toBeInTheDocument();
  });

  it("renders an unrecognized future status value safely instead of crashing", async () => {
    signIn();
    seedToolCatalog(FIXTURE_WORKSPACE_ACME.id, []);
    seedToolExecutions(FIXTURE_WORKSPACE_ACME.id, [
      makeToolExecutionFixture({
        id: "exec-1",
        agent_run_id: RUN_1,
        tool_definition_id: TOOL_ECHO,
        tool_key: "demo.echo",
        status: "queued_upstream" as never,
      }),
    ]);

    renderAuthenticated(
      <ToolExecutionList
        workspaceId={FIXTURE_WORKSPACE_ACME.id}
        runId={RUN_1}
        runStatus="running"
      />,
    );

    expect(await screen.findByText("demo.echo")).toBeInTheDocument();
    expect(screen.getByText("queued_upstream")).toBeInTheDocument();
  });

  it("shows a network-error state and recovers via Retry", async () => {
    signIn();
    toolExecutionMockState.listNetworkError = true;

    renderAuthenticated(
      <ToolExecutionList
        workspaceId={FIXTURE_WORKSPACE_ACME.id}
        runId={RUN_1}
        runStatus="succeeded"
      />,
    );

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();

    toolExecutionMockState.listNetworkError = false;
    seedToolCatalog(FIXTURE_WORKSPACE_ACME.id, []);
    seedToolExecutions(FIXTURE_WORKSPACE_ACME.id, [
      makeToolExecutionFixture({
        id: "exec-1",
        agent_run_id: RUN_1,
        tool_definition_id: TOOL_ECHO,
        tool_key: "demo.echo",
      }),
    ]);
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("demo.echo")).toBeInTheDocument();
  });

  it("never offers a manual Retry Tool / Run Tool / Execute action", async () => {
    signIn();
    seedToolCatalog(FIXTURE_WORKSPACE_ACME.id, []);
    seedToolExecutions(FIXTURE_WORKSPACE_ACME.id, [
      makeToolExecutionFixture({
        id: "exec-1",
        agent_run_id: RUN_1,
        tool_definition_id: TOOL_ECHO,
        tool_key: "demo.echo",
        status: "failed",
      }),
    ]);

    renderAuthenticated(
      <ToolExecutionList
        workspaceId={FIXTURE_WORKSPACE_ACME.id}
        runId={RUN_1}
        runStatus="failed"
      />,
    );

    await screen.findByText("demo.echo");
    expect(screen.queryByRole("button", { name: /retry tool/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /run tool/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /execute/i })).not.toBeInTheDocument();
  });
});
