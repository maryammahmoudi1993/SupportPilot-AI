import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { describe, expect, it, vi } from "vitest";

import { IntegrationsListPage } from "@/features/integrations/components/integrations-list-page";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { FIXTURE_USER, FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX, mockState } from "@/tests/msw/handlers";
import {
  makeWebhookEndpointFixture,
  seedWebhookEndpoints,
  webhookMockState,
} from "@/tests/msw/webhook-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(),
  usePathname: vi.fn(),
  useSearchParams: vi.fn(),
}));

function setupNavigationMocks(initialQuery = "?tab=webhooks") {
  const replace = vi.fn();
  vi.mocked(useRouter).mockReturnValue({ replace } as unknown as ReturnType<typeof useRouter>);
  vi.mocked(usePathname).mockReturnValue("/app/integrations");
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams(initialQuery) as unknown as ReturnType<typeof useSearchParams>,
  );
  return { replace };
}

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

describe("WebhookEndpointsTab (via IntegrationsListPage)", () => {
  it("renders real endpoint rows returned by the API", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedWebhookEndpoints(FIXTURE_WORKSPACE_ACME.id, [
      makeWebhookEndpointFixture({
        id: "ep-1",
        name: "Support ops relay",
        status: "active",
        secret_configured: true,
      }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<IntegrationsListPage />);

    expect(await screen.findByRole("link", { name: "Support ops relay" })).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByText("Active")).toBeInTheDocument();
    expect(within(table).getByText("Configured")).toBeInTheDocument();
  });

  it("shows a distinct empty state for zero endpoints", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    setupNavigationMocks();

    renderAuthenticated(<IntegrationsListPage />);

    expect(await screen.findByText("No webhook endpoints yet")).toBeInTheDocument();
  });

  it("shows a network-error state (not empty) and recovers via Retry", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    webhookMockState.endpointListNetworkError = true;
    setupNavigationMocks();

    renderAuthenticated(<IntegrationsListPage />);

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();

    webhookMockState.endpointListNetworkError = false;
    seedWebhookEndpoints(FIXTURE_WORKSPACE_ACME.id, [
      makeWebhookEndpointFixture({ id: "ep-1", name: "Recovered endpoint" }),
    ]);
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("link", { name: "Recovered endpoint" })).toBeInTheDocument();
  });

  it("never renders unknown/unrecognized status as a crash — falls back to the raw value", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedWebhookEndpoints(FIXTURE_WORKSPACE_ACME.id, [
      makeWebhookEndpointFixture({
        id: "ep-1",
        name: "Future endpoint",
        status: "pending_migration" as unknown as "active",
      }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<IntegrationsListPage />);

    expect(await screen.findByText("pending_migration")).toBeInTheDocument();
  });

  it("switches to this tab via the URL and keeps Connections state out of it", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    setupNavigationMocks("?tab=webhooks");

    renderAuthenticated(<IntegrationsListPage />);

    expect(await screen.findByText("No webhook endpoints yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Webhooks" })).toHaveAttribute("aria-current", "page");
  });

  it("never renders another workspace's endpoints while/after switching workspaces", async () => {
    signIn([FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX]);
    seedWebhookEndpoints(FIXTURE_WORKSPACE_ACME.id, [
      makeWebhookEndpointFixture({ id: "acme-ep", name: "Acme-only endpoint" }),
    ]);
    seedWebhookEndpoints(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeWebhookEndpointFixture({ id: "globex-ep", name: "Globex-only endpoint" }),
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

    expect(await screen.findByRole("link", { name: "Acme-only endpoint" })).toBeInTheDocument();

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: `switch-to-${FIXTURE_WORKSPACE_GLOBEX.name}` }));

    await waitFor(() =>
      expect(screen.queryByRole("link", { name: "Acme-only endpoint" })).not.toBeInTheDocument(),
    );
    expect(await screen.findByRole("link", { name: "Globex-only endpoint" })).toBeInTheDocument();
  });

  it("never renders a create/edit/delete/enable-disable control (deferred to a later chunk)", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]); // admin — canManageWebhooks would be true if manage roles applied
    seedWebhookEndpoints(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeWebhookEndpointFixture({ id: "ep-1", name: "Some endpoint" }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<IntegrationsListPage />);
    await screen.findByRole("link", { name: "Some endpoint" });

    expect(screen.queryByRole("button", { name: /new endpoint/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^delete$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^disable$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /rotate secret/i })).not.toBeInTheDocument();
  });
});
