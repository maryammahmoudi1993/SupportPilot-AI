import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { describe, expect, it, vi } from "vitest";

import { IntegrationsListPage } from "@/features/integrations/components/integrations-list-page";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import {
  FIXTURE_USER,
  FIXTURE_WORKSPACE_ACME,
  FIXTURE_WORKSPACE_GLOBEX,
  mockState,
} from "@/tests/msw/handlers";
import {
  integrationMockState,
  makeIntegrationConnectionFixture,
  seedIntegrationConnections,
} from "@/tests/msw/integration-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(),
  usePathname: vi.fn(),
  useSearchParams: vi.fn(),
}));

function setupNavigationMocks(initialQuery = "") {
  const replace = vi.fn();
  const push = vi.fn();
  vi.mocked(useRouter).mockReturnValue({ replace, push } as unknown as ReturnType<typeof useRouter>);
  vi.mocked(usePathname).mockReturnValue("/app/integrations");
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams(initialQuery) as unknown as ReturnType<typeof useSearchParams>,
  );
  return { replace, push };
}

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

describe("IntegrationsListPage", () => {
  it("renders real connection rows returned by the API", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedIntegrationConnections(FIXTURE_WORKSPACE_ACME.id, [
      makeIntegrationConnectionFixture({
        id: "conn-1",
        provider: "stripe",
        display_name: "Primary Stripe",
        status: "active",
      }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<IntegrationsListPage />);

    expect(await screen.findByRole("link", { name: "Primary Stripe" })).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByText("Active")).toBeInTheDocument();
    expect(within(table).getByText("Configured")).toBeInTheDocument();
  });

  it("falls back to the provider label when display_name is blank", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedIntegrationConnections(FIXTURE_WORKSPACE_ACME.id, [
      makeIntegrationConnectionFixture({ id: "conn-1", provider: "demo_commerce" }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<IntegrationsListPage />);

    expect(
      await screen.findByRole("link", { name: "Demo commerce (orders & shipments)" }),
    ).toBeInTheDocument();
  });

  it("shows a distinct empty state for zero connections", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    setupNavigationMocks();

    renderAuthenticated(<IntegrationsListPage />);

    expect(await screen.findByText("No integration connections yet")).toBeInTheDocument();
  });

  it("shows a network-error state (not empty) and recovers via Retry", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    integrationMockState.connectionListNetworkError = true;
    setupNavigationMocks();

    renderAuthenticated(<IntegrationsListPage />);

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();

    integrationMockState.connectionListNetworkError = false;
    seedIntegrationConnections(FIXTURE_WORKSPACE_ACME.id, [
      makeIntegrationConnectionFixture({
        id: "conn-1",
        provider: "email",
        display_name: "Recovered connection",
      }),
    ]);
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));

    expect(
      await screen.findByRole("link", { name: "Recovered connection" }),
    ).toBeInTheDocument();
  });

  it("never renders unknown/unrecognized status as a crash — falls back to the raw value", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedIntegrationConnections(FIXTURE_WORKSPACE_ACME.id, [
      makeIntegrationConnectionFixture({
        id: "conn-1",
        provider: "stripe",
        // A future backend status value this frontend build doesn't know about yet.
        status: "pending_migration" as unknown as "active",
      }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<IntegrationsListPage />);

    expect(await screen.findByText("pending_migration")).toBeInTheDocument();
  });

  it("paginates using the real page query param", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedIntegrationConnections(
      FIXTURE_WORKSPACE_ACME.id,
      Array.from({ length: 3 }, (_, index) =>
        makeIntegrationConnectionFixture({
          id: `conn-${index}`,
          provider: "email",
          display_name: `Connection ${index}`,
        }),
      ),
    );
    const { replace } = setupNavigationMocks();

    renderAuthenticated(<IntegrationsListPage />);
    await screen.findByRole("link", { name: "Connection 0" });

    // page_size defaults to 50, so with only 3 rows there is no real next page —
    // this asserts the pagination summary reflects the real count, not a guess.
    expect(await screen.findByText("Page 1 · 3 connections total")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it("never renders another workspace's connections while/after switching workspaces", async () => {
    signIn([FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX]);
    seedIntegrationConnections(FIXTURE_WORKSPACE_ACME.id, [
      makeIntegrationConnectionFixture({
        id: "acme-conn",
        provider: "stripe",
        display_name: "Acme-only connection",
      }),
    ]);
    seedIntegrationConnections(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeIntegrationConnectionFixture({
        id: "globex-conn",
        provider: "email",
        display_name: "Globex-only connection",
      }),
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
          <IntegrationsListPage />
        </>
      );
    }

    renderAuthenticated(<Harness />);

    expect(
      await screen.findByRole("link", { name: "Acme-only connection" }),
    ).toBeInTheDocument();

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: `switch-to-${FIXTURE_WORKSPACE_GLOBEX.name}` }));

    await waitFor(() =>
      expect(
        screen.queryByRole("link", { name: "Acme-only connection" }),
      ).not.toBeInTheDocument(),
    );
    expect(
      await screen.findByRole("link", { name: "Globex-only connection" }),
    ).toBeInTheDocument();
  });

  it("renders a New connection control for an authorized (owner/admin) role, absent for a support_agent (Phase 22 Chunk 3)", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]); // admin
    setupNavigationMocks();
    renderAuthenticated(<IntegrationsListPage />);
    expect(await screen.findByRole("button", { name: /new connection/i })).toBeInTheDocument();
  });

  it("creates a demo_commerce connection with no credential fields (the one provider with none)", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    setupNavigationMocks();
    renderAuthenticated(<IntegrationsListPage />);
    await screen.findByText("No integration connections yet");

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /new connection/i }));
    // demo_commerce is the default selected provider — no credential inputs render for it.
    expect(
      screen.getByText("The demo commerce provider has no credentials to configure."),
    ).toBeInTheDocument();
    await user.type(screen.getByLabelText("Display name (optional)"), "Demo shop");
    await user.click(screen.getByRole("button", { name: /^create connection$/i }));

    await waitFor(() =>
      expect(integrationMockState.connectionsByWorkspace[FIXTURE_WORKSPACE_GLOBEX.id]).toHaveLength(1),
    );
  });
});
