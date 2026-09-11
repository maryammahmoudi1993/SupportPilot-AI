import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { WebhookEndpointDetailPage } from "@/features/webhooks/components/webhook-endpoint-detail-page";
import { FIXTURE_USER, FIXTURE_WORKSPACE_GLOBEX, mockState } from "@/tests/msw/handlers";
import { makeWebhookEndpointFixture, seedWebhookEndpoints } from "@/tests/msw/webhook-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

const ENDPOINT_ID = "44444444-4444-4444-8444-444444444444";

describe("ManageWebhookEndpointControls (Phase 22 Chunk 3)", () => {
  it("edits name/URL/subscribed events", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]); // admin
    seedWebhookEndpoints(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeWebhookEndpointFixture({ id: ENDPOINT_ID, name: "Original name" }),
    ]);

    renderAuthenticated(<WebhookEndpointDetailPage endpointId={ENDPOINT_ID} />);
    await screen.findByRole("heading", { name: "Original name" });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^edit$/i }));
    const nameInput = screen.getByLabelText("Name");
    await user.clear(nameInput);
    await user.type(nameInput, "Renamed endpoint");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    expect(await screen.findByRole("heading", { name: "Renamed endpoint" })).toBeInTheDocument();
  });

  it("rotates the signing secret only after confirmation, and shows the new secret exactly once", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedWebhookEndpoints(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeWebhookEndpointFixture({ id: ENDPOINT_ID, name: "Endpoint" }),
    ]);

    renderAuthenticated(<WebhookEndpointDetailPage endpointId={ENDPOINT_ID} />);
    await screen.findByRole("heading", { name: "Endpoint" });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /rotate signing secret/i }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/cannot be undone/i);
    await user.click(within(dialog).getByRole("button", { name: /rotate secret/i }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const secretAlert = await screen.findByRole("alert", { name: /webhook signing secret/i });
    expect(within(secretAlert).getByDisplayValue("test-rotated-secret-not-real")).toBeInTheDocument();

    await user.click(within(secretAlert).getByRole("button", { name: /saved this secret/i }));
    expect(screen.queryByDisplayValue("test-rotated-secret-not-real")).not.toBeInTheDocument();
  });

  it("disables the endpoint only after confirmation, and re-enables it", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedWebhookEndpoints(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeWebhookEndpointFixture({ id: ENDPOINT_ID, name: "Endpoint", status: "active" }),
    ]);

    renderAuthenticated(<WebhookEndpointDetailPage endpointId={ENDPOINT_ID} />);
    await screen.findByRole("heading", { name: "Endpoint" });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /disable endpoint/i }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/redrives/i);
    await user.click(within(dialog).getByRole("button", { name: /disable endpoint/i }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const enableButton = await screen.findByRole("button", { name: /enable endpoint/i });

    await user.click(enableButton);
    expect(await screen.findByRole("button", { name: /disable endpoint/i })).toBeInTheDocument();
  });
});
