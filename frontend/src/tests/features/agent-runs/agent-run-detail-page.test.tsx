import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AgentRunDetailPage } from "@/features/agent-runs/components/agent-run-detail-page";
import {
  FIXTURE_USER,
  FIXTURE_WORKSPACE_ACME,
  FIXTURE_WORKSPACE_GLOBEX,
  mockState,
} from "@/tests/msw/handlers";
import {
  agentRunMockState,
  makeAgentRunFixture,
  makeAgentStepFixture,
  seedAgentRuns,
  seedAgentSteps,
} from "@/tests/msw/agent-run-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

const RUN_1 = "11111111-1111-4111-8111-111111111111";
const GLOBEX_RUN = "22222222-2222-4222-8222-222222222222";
const VERSION_1 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const CONV_1 = "44444444-4444-4444-8444-444444444444";
const TICKET_1 = "55555555-5555-4555-8555-555555555555";

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

describe("AgentRunDetailPage", () => {
  it("renders real run fields, a real conversation link, and a real ticket link", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedAgentRuns(FIXTURE_WORKSPACE_ACME.id, [
      makeAgentRunFixture({
        id: RUN_1,
        agent_version_id: VERSION_1,
        conversation_id: CONV_1,
        ticket_id: TICKET_1,
        status: "succeeded",
        trigger: "conversation",
        final_response: "Your refund has been processed.",
        total_tokens: 456,
      }),
    ]);
    seedAgentSteps(RUN_1, [
      makeAgentStepFixture({ id: "step-1", sequence: 1, step_type: "run_started" }),
    ]);

    renderAuthenticated(<AgentRunDetailPage runId={RUN_1} />);

    expect(
      await screen.findByRole("heading", { name: `Run #${RUN_1.slice(0, 8)}` }),
    ).toBeInTheDocument();
    // "Succeeded" appears twice — once for the run status, once for the step
    // status badge in the trace below — so assert presence, not uniqueness.
    expect(screen.getAllByText("Succeeded").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Your refund has been processed.")).toBeInTheDocument();
    expect(screen.getByText("456")).toBeInTheDocument();

    expect(screen.getByRole("link", { name: "View originating conversation" })).toHaveAttribute(
      "href",
      `/app/inbox/${CONV_1}`,
    );
    expect(screen.getByRole("link", { name: "View related ticket" })).toHaveAttribute(
      "href",
      `/app/tickets/${TICKET_1}`,
    );
    expect(await screen.findByText("run_started")).toBeInTheDocument();
  });

  it("shows a failure block with the safe failure code/message when the run failed", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedAgentRuns(FIXTURE_WORKSPACE_ACME.id, [
      makeAgentRunFixture({
        id: RUN_1,
        agent_version_id: VERSION_1,
        status: "failed",
        failure_code: "provider_timeout",
        failure_message_safe: "The provider did not respond in time.",
      }),
    ]);
    seedAgentSteps(RUN_1, []);

    renderAuthenticated(<AgentRunDetailPage runId={RUN_1} />);

    expect(await screen.findByText("The provider did not respond in time.")).toBeInTheDocument();
    expect(screen.getByText(/provider_timeout/)).toBeInTheDocument();
  });

  it("shows the honest no-conversation/no-ticket notes when a run isn't tied to either", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedAgentRuns(FIXTURE_WORKSPACE_ACME.id, [
      makeAgentRunFixture({ id: RUN_1, agent_version_id: VERSION_1, trigger: "manual" }),
    ]);
    seedAgentSteps(RUN_1, []);

    renderAuthenticated(<AgentRunDetailPage runId={RUN_1} />);

    expect(await screen.findByText("— (not tied to a conversation)")).toBeInTheDocument();
    expect(screen.getByText("— (not tied to a ticket)")).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "View originating conversation" }),
    ).not.toBeInTheDocument();
  });

  it("shows a safe not-found state for a confirmed 404", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);

    renderAuthenticated(<AgentRunDetailPage runId="00000000-0000-4000-8000-000000000000" />);

    expect(await screen.findByText("Agent run not found")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Agent Runs" })).toHaveAttribute(
      "href",
      "/app/agent-runs",
    );
  });

  it("shows a safe not-found state for a run belonging to a different workspace — never leaked", async () => {
    signIn([FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX]);
    seedAgentRuns(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeAgentRunFixture({
        id: GLOBEX_RUN,
        agent_version_id: VERSION_1,
        final_response: "Globex-only response",
      }),
    ]);
    // Active workspace defaults to Acme; the run above belongs to Globex.

    renderAuthenticated(<AgentRunDetailPage runId={GLOBEX_RUN} />);

    expect(await screen.findByText("Agent run not found")).toBeInTheDocument();
    expect(screen.queryByText("Globex-only response")).not.toBeInTheDocument();
  });

  it("rejects a malformed route ID without ever making a network request", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    agentRunMockState.detailNetworkError = true; // would fail loudly if a request were made

    renderAuthenticated(<AgentRunDetailPage runId="not-a-uuid" />);

    expect(await screen.findByText("Agent run not found")).toBeInTheDocument();
  });

  it("shows a network-error state (not not-found) and recovers via Retry", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    agentRunMockState.detailNetworkError = true;

    renderAuthenticated(<AgentRunDetailPage runId={RUN_1} />);

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
    expect(screen.queryByText("Agent run not found")).not.toBeInTheDocument();

    agentRunMockState.detailNetworkError = false;
    seedAgentRuns(FIXTURE_WORKSPACE_ACME.id, [
      makeAgentRunFixture({ id: RUN_1, agent_version_id: VERSION_1, final_response: "Recovered" }),
    ]);
    seedAgentSteps(RUN_1, []);
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("Recovered")).toBeInTheDocument();
  });

  it("renders an unrecognized future status value safely instead of crashing", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedAgentRuns(FIXTURE_WORKSPACE_ACME.id, [
      makeAgentRunFixture({ id: RUN_1, agent_version_id: VERSION_1, status: "queued" as never }),
    ]);
    seedAgentSteps(RUN_1, []);

    renderAuthenticated(<AgentRunDetailPage runId={RUN_1} />);

    expect(
      await screen.findByRole("heading", { name: `Run #${RUN_1.slice(0, 8)}` }),
    ).toBeInTheDocument();
    expect(screen.getByText("queued")).toBeInTheDocument();
  });
});
