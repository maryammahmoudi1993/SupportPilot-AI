import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { describe, expect, it, vi } from "vitest";

import { IntegrationsListPage } from "@/features/integrations/components/integrations-list-page";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { FIXTURE_USER, FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX, mockState } from "@/tests/msw/handlers";
import {
  makeWebhookDeliveryFixture,
  seedWebhookDeliveries,
  webhookMockState,
} from "@/tests/msw/webhook-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(),
  usePathname: vi.fn(),
  useSearchParams: vi.fn(),
}));

function setupNavigationMocks(initialQuery = "?tab=deliveries") {
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

describe("WebhookDeliveriesTab (via IntegrationsListPage)", () => {
  it("renders real delivery rows returned by the API", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedWebhookDeliveries(FIXTURE_WORKSPACE_ACME.id, [
      makeWebhookDeliveryFixture({
        delivery_id: "d1",
        endpoint_id: "ep-1",
        endpoint_name: "Support ops relay",
        event_type: "approval.requested",
        status: "delivered",
        last_http_status: 200,
      }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<IntegrationsListPage />);

    expect(await screen.findByRole("link", { name: "Approval requested" })).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByText("Support ops relay")).toBeInTheDocument();
    expect(within(table).getByText("Delivered")).toBeInTheDocument();
    expect(within(table).getByText("200")).toBeInTheDocument();
  });

  it("shows a distinct empty state for zero deliveries", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    setupNavigationMocks();

    renderAuthenticated(<IntegrationsListPage />);

    expect(await screen.findByText("No webhook deliveries yet")).toBeInTheDocument();
  });

  it("shows a network-error state (not empty) and recovers via Retry", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    webhookMockState.deliveryListNetworkError = true;
    setupNavigationMocks();

    renderAuthenticated(<IntegrationsListPage />);

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();

    webhookMockState.deliveryListNetworkError = false;
    seedWebhookDeliveries(FIXTURE_WORKSPACE_ACME.id, [
      makeWebhookDeliveryFixture({
        delivery_id: "d1",
        endpoint_id: "ep-1",
        endpoint_name: "Recovered endpoint",
      }),
    ]);
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("Recovered endpoint")).toBeInTheDocument();
  });

  it("renders every real delivery status, including an unrecognized future one, without crashing", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedWebhookDeliveries(FIXTURE_WORKSPACE_ACME.id, [
      makeWebhookDeliveryFixture({
        delivery_id: "d1",
        endpoint_id: "ep-1",
        endpoint_name: "Endpoint",
        status: "pending",
        last_http_status: null,
      }),
      makeWebhookDeliveryFixture({
        delivery_id: "d2",
        endpoint_id: "ep-1",
        endpoint_name: "Endpoint",
        status: "future_status",
        event_type: "handoff.created",
      }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<IntegrationsListPage />);

    expect(await screen.findByText("Pending")).toBeInTheDocument();
    expect(await screen.findByText("future_status")).toBeInTheDocument();
  });

  it("never renders another workspace's deliveries while/after switching workspaces", async () => {
    signIn([FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX]);
    seedWebhookDeliveries(FIXTURE_WORKSPACE_ACME.id, [
      makeWebhookDeliveryFixture({
        delivery_id: "acme-d",
        endpoint_id: "ep-a",
        endpoint_name: "Acme-only delivery endpoint",
      }),
    ]);
    seedWebhookDeliveries(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeWebhookDeliveryFixture({
        delivery_id: "globex-d",
        endpoint_id: "ep-b",
        endpoint_name: "Globex-only delivery endpoint",
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

    expect(await screen.findByText("Acme-only delivery endpoint")).toBeInTheDocument();

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: `switch-to-${FIXTURE_WORKSPACE_GLOBEX.name}` }));

    await waitFor(() =>
      expect(screen.queryByText("Acme-only delivery endpoint")).not.toBeInTheDocument(),
    );
    expect(await screen.findByText("Globex-only delivery endpoint")).toBeInTheDocument();
  });

  it("never renders a redrive/retry control on the list", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedWebhookDeliveries(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeWebhookDeliveryFixture({
        delivery_id: "d1",
        endpoint_id: "ep-1",
        endpoint_name: "Failed delivery endpoint",
        status: "failed",
      }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<IntegrationsListPage />);
    await screen.findByText("Failed delivery endpoint");

    expect(screen.queryByRole("button", { name: /redrive/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^retry$/i })).not.toBeInTheDocument();
  });
});
