import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { describe, expect, it, vi } from "vitest";

import { TicketsListPage } from "@/features/tickets/components/tickets-list-page";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import {
  FIXTURE_USER,
  FIXTURE_WORKSPACE_ACME,
  FIXTURE_WORKSPACE_GLOBEX,
  mockState,
} from "@/tests/msw/handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";
import { makeTicketFixture, seedTickets, ticketMockState } from "@/tests/msw/ticket-handlers";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(),
  usePathname: vi.fn(),
  useSearchParams: vi.fn(),
}));

function setupNavigationMocks(initialQuery = "") {
  const replace = vi.fn();
  vi.mocked(useRouter).mockReturnValue({ replace } as unknown as ReturnType<typeof useRouter>);
  vi.mocked(usePathname).mockReturnValue("/app/tickets");
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams(initialQuery) as unknown as ReturnType<typeof useSearchParams>,
  );
  return { replace };
}

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

const CUSTOMER_1 = "11111111-1111-4111-8111-111111111111";

describe("TicketsListPage", () => {
  it("renders real ticket rows returned by the API", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedTickets(FIXTURE_WORKSPACE_ACME.id, [
      makeTicketFixture({
        id: "tick-1",
        customer_id: CUSTOMER_1,
        subject: "Refund request",
        status: "open",
        priority: "high",
      }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<TicketsListPage />);

    expect(await screen.findByRole("link", { name: "Refund request" })).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByText("Open")).toBeInTheDocument();
    expect(within(table).getByText("High")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: `Customer #${CUSTOMER_1.slice(0, 8)}` }),
    ).toHaveAttribute("href", `/app/customers/${CUSTOMER_1}`);
  });

  it("shows a distinct empty state for zero tickets", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    setupNavigationMocks();

    renderAuthenticated(<TicketsListPage />);

    expect(await screen.findByText("No tickets yet")).toBeInTheDocument();
  });

  it("shows a network-error state (not empty) and recovers via Retry", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    ticketMockState.listNetworkError = true;
    setupNavigationMocks();

    renderAuthenticated(<TicketsListPage />);

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
    expect(screen.queryByText("No tickets yet")).not.toBeInTheDocument();

    ticketMockState.listNetworkError = false;
    seedTickets(FIXTURE_WORKSPACE_ACME.id, [
      makeTicketFixture({ id: "tick-1", customer_id: CUSTOMER_1, subject: "Recovered" }),
    ]);
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("link", { name: "Recovered" })).toBeInTheDocument();
  });

  it("pushes a status filter change into the URL with the page reset to 1", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    const { replace } = setupNavigationMocks("page=3");

    renderAuthenticated(<TicketsListPage />);
    await screen.findByText("No tickets yet");

    await userEvent.setup().selectOptions(screen.getByLabelText("Status"), "open");

    expect(replace).toHaveBeenCalledWith("/app/tickets?status=open", { scroll: false });
  });

  it("real ordering is server-driven — no client ordering control is offered", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    setupNavigationMocks();

    renderAuthenticated(<TicketsListPage />);
    await screen.findByText("No tickets yet");

    // No "ordering" schema parameter is real on this endpoint (dead
    // backend-side) — the UI must never offer a control implying it works.
    expect(screen.queryByLabelText(/sort|order/i)).not.toBeInTheDocument();
  });

  it("paginates using the backend's next/previous contract and preserves filters", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedTickets(
      FIXTURE_WORKSPACE_ACME.id,
      Array.from({ length: 55 }, (_, index) =>
        makeTicketFixture({
          id: `tick-${index}`,
          customer_id: CUSTOMER_1,
          subject: `Ticket ${index}`,
          status: "open",
        }),
      ),
    );
    const { replace } = setupNavigationMocks("status=open");

    renderAuthenticated(<TicketsListPage />);

    const nextButton = await screen.findByRole("button", { name: "Next page" });
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    expect(nextButton).toBeEnabled();

    await userEvent.setup().click(nextButton);

    expect(replace).toHaveBeenCalledWith("/app/tickets?page=2&status=open", { scroll: false });
  });

  it("shows a contextual customer filter banner from a real cross-domain link and can clear it", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedTickets(FIXTURE_WORKSPACE_ACME.id, [
      makeTicketFixture({ id: "tick-1", customer_id: CUSTOMER_1, subject: "For this customer" }),
    ]);
    const { replace } = setupNavigationMocks(`customer=${CUSTOMER_1}`);

    renderAuthenticated(<TicketsListPage />);

    expect(await screen.findByRole("link", { name: "For this customer" })).toBeInTheDocument();
    expect(screen.getByText(/Showing tickets for/)).toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole("button", { name: "Clear filter" }));

    expect(replace).toHaveBeenCalledWith("/app/tickets", { scroll: false });
  });

  it("renders an unrecognized future status/priority value safely instead of crashing", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedTickets(FIXTURE_WORKSPACE_ACME.id, [
      makeTicketFixture({
        id: "tick-1",
        customer_id: CUSTOMER_1,
        subject: "Future status",
        status: "escalated" as never,
        priority: "critical" as never,
      }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<TicketsListPage />);

    expect(await screen.findByRole("link", { name: "Future status" })).toBeInTheDocument();
    expect(screen.getByText("escalated")).toBeInTheDocument();
    expect(screen.getByText("critical")).toBeInTheDocument();
  });

  it("never renders another workspace's tickets while/after switching workspaces", async () => {
    signIn([FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX]);
    seedTickets(FIXTURE_WORKSPACE_ACME.id, [
      makeTicketFixture({ id: "acme-tick", customer_id: CUSTOMER_1, subject: "Acme Ticket" }),
    ]);
    seedTickets(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeTicketFixture({ id: "globex-tick", customer_id: CUSTOMER_1, subject: "Globex Ticket" }),
    ]);
    setupNavigationMocks();

    function Harness() {
      const workspace = useWorkspace();
      return (
        <>
          {workspace.status === "ready" &&
            workspace.workspaces.map((candidate) => (
              <button key={candidate.id} onClick={() => workspace.selectWorkspace(candidate.id)}>
                {`switch-to-${candidate.name}`}
              </button>
            ))}
          <TicketsListPage />
        </>
      );
    }

    renderAuthenticated(<Harness />);

    expect(await screen.findByRole("link", { name: "Acme Ticket" })).toBeInTheDocument();

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: `switch-to-${FIXTURE_WORKSPACE_GLOBEX.name}` }));

    await waitFor(() => expect(screen.queryByText("Acme Ticket")).not.toBeInTheDocument());
    expect(await screen.findByRole("link", { name: "Globex Ticket" })).toBeInTheDocument();
    expect(screen.queryByText("Acme Ticket")).not.toBeInTheDocument();
  });
});
