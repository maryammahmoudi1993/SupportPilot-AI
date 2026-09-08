import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { describe, expect, it, vi } from "vitest";

import { CustomersListPage } from "@/features/customers/components/customers-list-page";
import { useWorkspace } from "@/features/workspace/workspace-provider";
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
import { renderAuthenticated } from "@/tests/support/render-authenticated";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(),
  usePathname: vi.fn(),
  useSearchParams: vi.fn(),
}));

function setupNavigationMocks(initialQuery = "") {
  const replace = vi.fn();
  vi.mocked(useRouter).mockReturnValue({ replace } as unknown as ReturnType<typeof useRouter>);
  vi.mocked(usePathname).mockReturnValue("/app/customers");
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams(initialQuery) as unknown as ReturnType<typeof useSearchParams>,
  );
  return { replace };
}

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

describe("CustomersListPage", () => {
  it("renders real customer rows returned by the API", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedCustomers(FIXTURE_WORKSPACE_ACME.id, [
      makeCustomerFixture({ id: "c1", display_name: "Jane Doe", email: "jane@example.com" }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<CustomersListPage />);

    expect(await screen.findByRole("link", { name: "Jane Doe" })).toBeInTheDocument();
    expect(screen.getByText("jane@example.com")).toBeInTheDocument();
  });

  it("shows a distinct empty state for zero customers", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    setupNavigationMocks();

    renderAuthenticated(<CustomersListPage />);

    expect(await screen.findByText("No customers yet")).toBeInTheDocument();
  });

  it("shows a network-error state (not empty) and recovers via Retry", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    customerMockState.listNetworkError = true;
    setupNavigationMocks();

    renderAuthenticated(<CustomersListPage />);

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
    expect(screen.queryByText("No customers yet")).not.toBeInTheDocument();

    customerMockState.listNetworkError = false;
    seedCustomers(FIXTURE_WORKSPACE_ACME.id, [
      makeCustomerFixture({ id: "c1", display_name: "Jane Doe" }),
    ]);
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("link", { name: "Jane Doe" })).toBeInTheDocument();
  });

  it("debounces search input into a single URL update, not one per keystroke", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    const { replace } = setupNavigationMocks();
    const user = userEvent.setup();

    renderAuthenticated(<CustomersListPage />);
    const searchField = await screen.findByLabelText("Search customers");

    await user.type(searchField, "jane");
    expect(replace).not.toHaveBeenCalled();

    await waitFor(() => expect(replace).toHaveBeenCalledTimes(1), { timeout: 2000 });
    expect(replace).toHaveBeenCalledWith("/app/customers?search=jane", { scroll: false });
  });

  it("pushes a status filter change into the URL with the page reset to 1", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    const { replace } = setupNavigationMocks("page=3");

    renderAuthenticated(<CustomersListPage />);
    await screen.findByText("No customers yet");

    await userEvent.setup().selectOptions(screen.getByLabelText("Status"), "active");

    expect(replace).toHaveBeenCalledWith("/app/customers?status=active", { scroll: false });
  });

  it("paginates using the backend's next/previous contract and preserves filters", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedCustomers(
      FIXTURE_WORKSPACE_ACME.id,
      Array.from({ length: 55 }, (_, index) =>
        makeCustomerFixture({ id: `c${index}`, display_name: `Customer ${index}` }),
      ),
    );
    const { replace } = setupNavigationMocks("search=customer");

    renderAuthenticated(<CustomersListPage />);

    const nextButton = await screen.findByRole("button", { name: "Next page" });
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    expect(nextButton).toBeEnabled();

    await userEvent.setup().click(nextButton);

    expect(replace).toHaveBeenCalledWith("/app/customers?page=2&search=customer", { scroll: false });
  });

  it("never renders another workspace's customers while/after switching workspaces", async () => {
    signIn([FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX]);
    seedCustomers(FIXTURE_WORKSPACE_ACME.id, [
      makeCustomerFixture({ id: "acme-1", display_name: "Acme Customer" }),
    ]);
    seedCustomers(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeCustomerFixture({ id: "globex-1", display_name: "Globex Customer" }),
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
          <CustomersListPage />
        </>
      );
    }

    renderAuthenticated(<Harness />);

    expect(await screen.findByRole("link", { name: "Acme Customer" })).toBeInTheDocument();

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: `switch-to-${FIXTURE_WORKSPACE_GLOBEX.name}` }));

    // The old workspace's row must be gone immediately — never rendered
    // alongside or bridging into the new workspace's data.
    await waitFor(() => expect(screen.queryByText("Acme Customer")).not.toBeInTheDocument());
    expect(await screen.findByRole("link", { name: "Globex Customer" })).toBeInTheDocument();
    expect(screen.queryByText("Acme Customer")).not.toBeInTheDocument();
  });
});
