import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { TicketDetailPage } from "@/features/tickets/components/ticket-detail-page";
import {
  FIXTURE_USER,
  FIXTURE_WORKSPACE_ACME,
  FIXTURE_WORKSPACE_GLOBEX,
  mockState,
} from "@/tests/msw/handlers";
import { makeTicketFixture, seedTickets, ticketMockState } from "@/tests/msw/ticket-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

const TICK_1 = "11111111-1111-4111-8111-111111111111";
const GLOBEX_TICK = "22222222-2222-4222-8222-222222222222";
const CUSTOMER_1 = "33333333-3333-4333-8333-333333333333";
const CONV_1 = "44444444-4444-4444-8444-444444444444";

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

describe("TicketDetailPage", () => {
  it("renders real ticket fields, a real customer link, and a real conversation link", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedTickets(FIXTURE_WORKSPACE_ACME.id, [
      makeTicketFixture({
        id: TICK_1,
        customer_id: CUSTOMER_1,
        conversation_id: CONV_1,
        subject: "Refund request",
        description: "Customer wants a refund for order #4821.",
        status: "in_progress",
        priority: "urgent",
        assigned_to: { id: "m1", email: "agent@example.com", role: "support_agent" },
      }),
    ]);

    renderAuthenticated(<TicketDetailPage ticketId={TICK_1} />);

    expect(await screen.findByRole("heading", { name: "Refund request" })).toBeInTheDocument();
    expect(screen.getByText("In Progress")).toBeInTheDocument();
    expect(screen.getByText("Urgent")).toBeInTheDocument();
    expect(screen.getByText("agent@example.com")).toBeInTheDocument();
    expect(screen.getByText("Customer wants a refund for order #4821.")).toBeInTheDocument();

    expect(
      screen.getByRole("link", { name: `Customer #${CUSTOMER_1.slice(0, 8)}` }),
    ).toHaveAttribute("href", `/app/customers/${CUSTOMER_1}`);
    expect(screen.getByRole("link", { name: "View originating conversation" })).toHaveAttribute(
      "href",
      `/app/inbox/${CONV_1}`,
    );
  });

  it("renders the Description field as a valid <dl>/<dt>/<dd> group (regression: Chunk 4 axe finding)", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedTickets(FIXTURE_WORKSPACE_ACME.id, [
      makeTicketFixture({
        id: TICK_1,
        customer_id: CUSTOMER_1,
        subject: "Refund request",
        description: "Customer wants a refund for order #4821.",
      }),
    ]);

    renderAuthenticated(<TicketDetailPage ticketId={TICK_1} />);

    const descriptionLabel = await screen.findByText("Description");
    expect(descriptionLabel.tagName).toBe("DT");
    expect(descriptionLabel.closest("dl")).not.toBeNull();
    const descriptionValue = screen.getByText("Customer wants a refund for order #4821.");
    expect(descriptionValue.tagName).toBe("DD");
    expect(descriptionValue.closest("dl")).toBe(descriptionLabel.closest("dl"));
  });

  it("shows a plain no-conversation note when the ticket wasn't created from one", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedTickets(FIXTURE_WORKSPACE_ACME.id, [
      makeTicketFixture({
        id: TICK_1,
        customer_id: CUSTOMER_1,
        conversation_id: null,
        subject: "Direct ticket",
      }),
    ]);

    renderAuthenticated(<TicketDetailPage ticketId={TICK_1} />);

    expect(await screen.findByRole("heading", { name: "Direct ticket" })).toBeInTheDocument();
    expect(screen.getByText(/created directly, not from a conversation/)).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "View originating conversation" }),
    ).not.toBeInTheDocument();
  });

  it("shows a safe not-found state for a confirmed 404", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);

    renderAuthenticated(<TicketDetailPage ticketId="00000000-0000-4000-8000-000000000000" />);

    expect(await screen.findByText("Ticket not found")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Tickets" })).toHaveAttribute(
      "href",
      "/app/tickets",
    );
  });

  it("shows a safe not-found state for a ticket belonging to a different workspace — never leaked", async () => {
    signIn([FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX]);
    seedTickets(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeTicketFixture({
        id: GLOBEX_TICK,
        customer_id: CUSTOMER_1,
        subject: "Globex Only Ticket",
      }),
    ]);
    // Active workspace defaults to Acme; the ticket above belongs to Globex.

    renderAuthenticated(<TicketDetailPage ticketId={GLOBEX_TICK} />);

    expect(await screen.findByText("Ticket not found")).toBeInTheDocument();
    expect(screen.queryByText("Globex Only Ticket")).not.toBeInTheDocument();
  });

  it("rejects a malformed route ID without ever making a network request", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    ticketMockState.detailNetworkError = true; // would fail loudly if a request were made

    renderAuthenticated(<TicketDetailPage ticketId="not-a-uuid" />);

    expect(await screen.findByText("Ticket not found")).toBeInTheDocument();
  });

  it("shows a network-error state (not not-found) and recovers via Retry", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    ticketMockState.detailNetworkError = true;

    renderAuthenticated(<TicketDetailPage ticketId={TICK_1} />);

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
    expect(screen.queryByText("Ticket not found")).not.toBeInTheDocument();

    ticketMockState.detailNetworkError = false;
    seedTickets(FIXTURE_WORKSPACE_ACME.id, [
      makeTicketFixture({ id: TICK_1, customer_id: CUSTOMER_1, subject: "Recovered" }),
    ]);
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("heading", { name: "Recovered" })).toBeInTheDocument();
  });

  it("renders an unrecognized future status/priority value safely instead of crashing", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedTickets(FIXTURE_WORKSPACE_ACME.id, [
      makeTicketFixture({
        id: TICK_1,
        customer_id: CUSTOMER_1,
        subject: "Future status",
        status: "escalated" as never,
        priority: "critical" as never,
      }),
    ]);

    renderAuthenticated(<TicketDetailPage ticketId={TICK_1} />);

    expect(await screen.findByRole("heading", { name: "Future status" })).toBeInTheDocument();
    expect(screen.getByText("escalated")).toBeInTheDocument();
    expect(screen.getByText("critical")).toBeInTheDocument();
  });
});
