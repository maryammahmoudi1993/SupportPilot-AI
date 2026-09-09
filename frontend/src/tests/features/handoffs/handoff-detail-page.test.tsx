import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HandoffDetailPage } from "@/features/handoffs/components/handoff-detail-page";
import {
  FIXTURE_USER,
  FIXTURE_WORKSPACE_ACME,
  FIXTURE_WORKSPACE_GLOBEX,
  mockState,
} from "@/tests/msw/handlers";
import { makeHandoffFixture, seedHandoffs } from "@/tests/msw/handoff-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

const HANDOFF_1 = "11111111-1111-4111-8111-111111111111";
const CONV_1 = "22222222-2222-4222-8222-222222222222";
const RUN_1 = "33333333-3333-4333-8333-333333333333";
const TICKET_1 = "44444444-4444-4444-8444-444444444444";

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

describe("HandoffDetailPage", () => {
  it("renders real handoff fields plus real Conversation/AgentRun/Ticket links", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedHandoffs(FIXTURE_WORKSPACE_ACME.id, [
      makeHandoffFixture({
        id: HANDOFF_1,
        conversation_id: CONV_1,
        agent_run_id: RUN_1,
        ticket_id: TICKET_1,
        status: "pending",
        reason_code: "customer_requested",
        safe_summary: "Customer explicitly asked to speak with a human agent.",
      }),
    ]);

    renderAuthenticated(<HandoffDetailPage handoffId={HANDOFF_1} />);

    expect(
      await screen.findByRole("heading", { name: "Customer requested a human" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View conversation" })).toHaveAttribute(
      "href",
      `/app/inbox/${CONV_1}`,
    );
    expect(screen.getByRole("link", { name: "View agent run" })).toHaveAttribute(
      "href",
      `/app/agent-runs/${RUN_1}`,
    );
    expect(screen.getByRole("link", { name: "View related ticket" })).toHaveAttribute(
      "href",
      `/app/tickets/${TICKET_1}`,
    );
    expect(
      screen.getByText("Customer explicitly asked to speak with a human agent."),
    ).toBeInTheDocument();
  });

  it("shows honest no-run/no-ticket notes when a handoff isn't tied to either", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedHandoffs(FIXTURE_WORKSPACE_ACME.id, [
      makeHandoffFixture({
        id: HANDOFF_1,
        conversation_id: CONV_1,
        agent_run_id: null,
        ticket_id: null,
      }),
    ]);

    renderAuthenticated(<HandoffDetailPage handoffId={HANDOFF_1} />);

    expect(await screen.findByText("— (not tied to a run)")).toBeInTheDocument();
    expect(screen.getByText("— (not tied to a ticket)")).toBeInTheDocument();
  });

  it("renders an unrecognized future status value safely instead of crashing", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedHandoffs(FIXTURE_WORKSPACE_ACME.id, [
      makeHandoffFixture({
        id: HANDOFF_1,
        conversation_id: CONV_1,
        status: "mystery_status" as never,
      }),
    ]);

    renderAuthenticated(<HandoffDetailPage handoffId={HANDOFF_1} />);

    expect(await screen.findByText("mystery_status")).toBeInTheDocument();
  });

  it("shows a safe not-found state for a confirmed 404", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);

    renderAuthenticated(<HandoffDetailPage handoffId="00000000-0000-4000-8000-000000000000" />);

    expect(await screen.findByText("Handoff not found")).toBeInTheDocument();
  });

  it("shows a safe not-found state for a handoff belonging to a different workspace — never leaked", async () => {
    signIn([FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX]);
    seedHandoffs(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeHandoffFixture({
        id: HANDOFF_1,
        conversation_id: CONV_1,
        safe_summary: "Globex-only handoff summary",
      }),
    ]);
    // Active workspace defaults to Acme; the handoff above belongs to Globex.

    renderAuthenticated(<HandoffDetailPage handoffId={HANDOFF_1} />);

    expect(await screen.findByText("Handoff not found")).toBeInTheDocument();
    expect(screen.queryByText("Globex-only handoff summary")).not.toBeInTheDocument();
  });
});
