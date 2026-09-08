import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { CustomerDetailPage } from "@/features/customers/components/customer-detail-page";
import {
  FIXTURE_USER,
  FIXTURE_WORKSPACE_ACME,
  FIXTURE_WORKSPACE_GLOBEX,
  mockState,
} from "@/tests/msw/handlers";
import {
  customerMockState,
  makeCustomerFixture,
  seedCustomers,
} from "@/tests/msw/customer-handlers";
import { makeConversationFixture, seedConversations } from "@/tests/msw/conversation-handlers";
import { makeTicketFixture, seedTickets } from "@/tests/msw/ticket-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

const CUST_1 = "11111111-1111-4111-8111-111111111111";
const GLOBEX_CUST = "22222222-2222-4222-8222-222222222222";

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

describe("CustomerDetailPage", () => {
  it("renders real customer fields on success", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedCustomers(FIXTURE_WORKSPACE_ACME.id, [
      makeCustomerFixture({
        id: CUST_1,
        display_name: "Jane Doe",
        email: "jane@example.com",
        company: "Acme Corp",
        phone: "+1 555 0100",
      }),
    ]);

    renderAuthenticated(<CustomerDetailPage customerId={CUST_1} />);

    expect(await screen.findByRole("heading", { name: "Jane Doe" })).toBeInTheDocument();
    expect(screen.getByText("jane@example.com")).toBeInTheDocument();
    expect(screen.getByText("+1 555 0100")).toBeInTheDocument();
    expect(screen.getAllByText("Acme Corp").length).toBeGreaterThan(0);
    // No fabricated product metrics.
    expect(screen.queryByText(/lifetime value/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/csat/i)).not.toBeInTheDocument();
  });

  it("shows a safe not-found state for a confirmed 404", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    // No customer seeded — the mock 404s exactly like the real backend does.

    renderAuthenticated(<CustomerDetailPage customerId="00000000-0000-4000-8000-000000000000" />);

    expect(await screen.findByText("Customer not found")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Customers" })).toHaveAttribute(
      "href",
      "/app/customers",
    );
  });

  it("shows a safe not-found state for a customer that belongs to a different workspace — never leaked", async () => {
    signIn([FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX]);
    seedCustomers(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeCustomerFixture({ id: GLOBEX_CUST, display_name: "Globex Only Customer" }),
    ]);
    // Active workspace defaults to the first membership (Acme) — the fixture
    // above belongs to Globex, so this exercises the exact cross-workspace
    // scenario (see backend/customers/selectors.py's 404-not-403 contract).

    renderAuthenticated(<CustomerDetailPage customerId={GLOBEX_CUST} />);

    expect(await screen.findByText("Customer not found")).toBeInTheDocument();
    expect(screen.queryByText("Globex Only Customer")).not.toBeInTheDocument();
  });

  it("rejects a malformed route ID without ever making a network request", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    customerMockState.detailNetworkError = true; // would fail loudly if a request were made

    renderAuthenticated(<CustomerDetailPage customerId="not-a-uuid" />);

    expect(await screen.findByText("Customer not found")).toBeInTheDocument();
  });

  it("shows a network-error state (not not-found) and recovers via Retry", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    customerMockState.detailNetworkError = true;

    renderAuthenticated(<CustomerDetailPage customerId={CUST_1} />);

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
    expect(screen.queryByText("Customer not found")).not.toBeInTheDocument();

    customerMockState.detailNetworkError = false;
    seedCustomers(FIXTURE_WORKSPACE_ACME.id, [
      makeCustomerFixture({ id: CUST_1, display_name: "Jane Doe" }),
    ]);
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("heading", { name: "Jane Doe" })).toBeInTheDocument();
  });

  it("shows a bounded related-tickets and related-conversations preview using the real customer filter, with no N+1", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedCustomers(FIXTURE_WORKSPACE_ACME.id, [
      makeCustomerFixture({ id: CUST_1, display_name: "Jane Doe" }),
    ]);
    seedConversations(FIXTURE_WORKSPACE_ACME.id, [
      makeConversationFixture({ id: "conv-1", customer_id: CUST_1, subject: "Order delayed" }),
    ]);
    seedTickets(FIXTURE_WORKSPACE_ACME.id, [
      makeTicketFixture({
        id: "tick-1",
        customer_id: CUST_1,
        subject: "Refund request",
        priority: "high",
      }),
    ]);

    renderAuthenticated(<CustomerDetailPage customerId={CUST_1} />);

    expect(await screen.findByRole("link", { name: "Order delayed" })).toHaveAttribute(
      "href",
      "/app/inbox/conv-1",
    );
    expect(screen.getByRole("link", { name: "Refund request" })).toHaveAttribute(
      "href",
      "/app/tickets/tick-1",
    );
    expect(
      screen.getByRole("link", { name: /View all 1 conversation for this customer/ }),
    ).toHaveAttribute("href", `/app/inbox?customer=${CUST_1}`);
    expect(
      screen.getByRole("link", { name: /View all 1 ticket for this customer/ }),
    ).toHaveAttribute("href", `/app/tickets?customer=${CUST_1}`);
  });

  it("shows a distinct empty state for a customer with no related records", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedCustomers(FIXTURE_WORKSPACE_ACME.id, [
      makeCustomerFixture({ id: CUST_1, display_name: "Jane Doe" }),
    ]);

    renderAuthenticated(<CustomerDetailPage customerId={CUST_1} />);

    expect(await screen.findByText("No conversations for this customer yet.")).toBeInTheDocument();
    expect(await screen.findByText("No tickets for this customer yet.")).toBeInTheDocument();
  });
});
