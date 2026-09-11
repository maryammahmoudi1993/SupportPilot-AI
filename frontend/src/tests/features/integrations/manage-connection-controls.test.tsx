import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { IntegrationConnectionDetailPage } from "@/features/integrations/components/integration-detail-page";
import { FIXTURE_USER, FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX, mockState } from "@/tests/msw/handlers";
import {
  integrationMockState,
  makeIntegrationConnectionFixture,
  seedIntegrationConnections,
} from "@/tests/msw/integration-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

const CONNECTION_ID = "22222222-2222-4222-8222-222222222222";

describe("ManageConnectionControls (Phase 22 Chunk 3)", () => {
  it("renders no manage controls for an unauthorized (support_agent) role", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]); // support_agent — not in owner/admin
    seedIntegrationConnections(FIXTURE_WORKSPACE_ACME.id, [
      makeIntegrationConnectionFixture({ id: CONNECTION_ID, provider: "demo_commerce" }),
    ]);

    renderAuthenticated(<IntegrationConnectionDetailPage connectionId={CONNECTION_ID} />);

    await screen.findByRole("heading", { level: 3 });
    expect(screen.queryByRole("button", { name: /^edit$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /rotate credentials/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /disable connection/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /test connection/i })).not.toBeInTheDocument();
  });

  it("edits display name and configuration for demo_commerce", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]); // admin
    seedIntegrationConnections(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeIntegrationConnectionFixture({
        id: CONNECTION_ID,
        provider: "demo_commerce",
        display_name: "Demo shop",
      }),
    ]);

    renderAuthenticated(<IntegrationConnectionDetailPage connectionId={CONNECTION_ID} />);
    await screen.findByRole("heading", { name: "Demo shop" });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^edit$/i }));

    const nameInput = screen.getByLabelText("Display name");
    await user.clear(nameInput);
    await user.type(nameInput, "Renamed demo shop");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    expect(await screen.findByRole("heading", { name: "Renamed demo shop" })).toBeInTheDocument();
  });

  it("rotates credentials only after an explicit confirmation, and never retains the submitted value", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedIntegrationConnections(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeIntegrationConnectionFixture({ id: CONNECTION_ID, provider: "stripe" }),
    ]);

    renderAuthenticated(<IntegrationConnectionDetailPage connectionId={CONNECTION_ID} />);
    await screen.findByRole("heading", { level: 3 });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /rotate credentials/i }));
    await user.type(screen.getByLabelText("Secret key"), "sk_live_not_a_real_secret_value");
    // Submitting the form opens the confirm dialog — the mutation has not fired yet.
    await user.click(screen.getByRole("button", { name: /^rotate credentials$/i }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/cannot be undone/i);
    await user.click(within(dialog).getByRole("button", { name: /^rotate credentials$/i }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    // The credential field is gone (form collapsed back to the "Rotate credentials" trigger) — never round-tripped.
    expect(screen.queryByLabelText("Secret key")).not.toBeInTheDocument();
  });

  it("requires confirmation before disabling, and shows the real server-confirmed status afterward", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedIntegrationConnections(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeIntegrationConnectionFixture({ id: CONNECTION_ID, provider: "demo_commerce", status: "active" }),
    ]);

    renderAuthenticated(<IntegrationConnectionDetailPage connectionId={CONNECTION_ID} />);
    await screen.findByRole("heading", { level: 3 });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /disable connection/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /disable connection/i }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(await screen.findByRole("button", { name: /enable connection/i })).toBeInTheDocument();
  });

  it("runs a test connection and shows the real result", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedIntegrationConnections(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeIntegrationConnectionFixture({ id: CONNECTION_ID, provider: "demo_commerce" }),
    ]);

    renderAuthenticated(<IntegrationConnectionDetailPage connectionId={CONNECTION_ID} />);
    await screen.findByRole("heading", { level: 3 });

    await userEvent.setup().click(screen.getByRole("button", { name: /test connection/i }));

    expect(await screen.findByText(/connection test succeeded/i)).toBeInTheDocument();
  });

  it("renders the real server error on a failed mutation, never a client-guessed outcome", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedIntegrationConnections(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeIntegrationConnectionFixture({ id: CONNECTION_ID, provider: "demo_commerce" }),
    ]);
    integrationMockState.mutationError = {
      code: "permission_denied",
      message: "You do not have permission to manage integration connections.",
      status: 403,
    };

    renderAuthenticated(<IntegrationConnectionDetailPage connectionId={CONNECTION_ID} />);
    await screen.findByRole("heading", { level: 3 });

    await userEvent.setup().click(screen.getByRole("button", { name: /test connection/i }));

    expect(
      await screen.findByText("You do not have permission to manage integration connections."),
    ).toBeInTheDocument();
  });
});
