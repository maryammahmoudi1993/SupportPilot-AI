import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WebhookEndpointDetailPage } from "@/features/webhooks/components/webhook-endpoint-detail-page";
import { FIXTURE_USER, FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX, mockState } from "@/tests/msw/handlers";
import { makeWebhookEndpointFixture, seedWebhookEndpoints } from "@/tests/msw/webhook-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

const ENDPOINT_ID = "11111111-1111-4111-8111-111111111111";

describe("WebhookEndpointDetailPage", () => {
  it("renders real safe endpoint detail fields, including the destination URL as plain text", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedWebhookEndpoints(FIXTURE_WORKSPACE_ACME.id, [
      makeWebhookEndpointFixture({
        id: ENDPOINT_ID,
        name: "Support ops relay",
        url: "https://ops.example.com/hooks/supportpilot",
        status: "active",
        subscribed_event_types: ["approval.requested", "handoff.created"],
        secret_configured: true,
      }),
    ]);

    renderAuthenticated(<WebhookEndpointDetailPage endpointId={ENDPOINT_ID} />);

    expect(await screen.findByRole("heading", { name: "Support ops relay" })).toBeInTheDocument();
    expect(screen.getByText("https://ops.example.com/hooks/supportpilot")).toBeInTheDocument();
    expect(screen.getByText("Configured")).toBeInTheDocument();
    expect(screen.getByText("approval.requested")).toBeInTheDocument();
    expect(screen.getByText("handoff.created")).toBeInTheDocument();
  });

  it("the destination URL is never rendered as a clickable link", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedWebhookEndpoints(FIXTURE_WORKSPACE_ACME.id, [
      makeWebhookEndpointFixture({
        id: ENDPOINT_ID,
        name: "Endpoint",
        url: "https://example.com/hooks",
      }),
    ]);

    renderAuthenticated(<WebhookEndpointDetailPage endpointId={ENDPOINT_ID} />);

    await screen.findByRole("heading", { name: "Endpoint" });
    expect(screen.queryByRole("link", { name: /example\.com/i })).not.toBeInTheDocument();
  });

  it("never renders the signing secret — only the safe configured indicator", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedWebhookEndpoints(FIXTURE_WORKSPACE_ACME.id, [
      makeWebhookEndpointFixture({ id: ENDPOINT_ID, name: "Endpoint", secret_configured: true }),
    ]);

    renderAuthenticated(<WebhookEndpointDetailPage endpointId={ENDPOINT_ID} />);

    await screen.findByRole("heading", { name: "Endpoint" });
    expect(document.body.innerHTML).not.toMatch(/encrypted_signing_secret/i);
    expect(document.body.innerHTML).not.toMatch(/"signing_secret"\s*:/i);
  });

  it("shows a not-configured state for a real endpoint with no secret yet", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedWebhookEndpoints(FIXTURE_WORKSPACE_ACME.id, [
      makeWebhookEndpointFixture({
        id: ENDPOINT_ID,
        name: "Endpoint",
        secret_configured: false,
        secret_created_at: null,
      }),
    ]);

    renderAuthenticated(<WebhookEndpointDetailPage endpointId={ENDPOINT_ID} />);

    await screen.findByRole("heading", { name: "Endpoint" });
    expect(screen.getByText("Not configured")).toBeInTheDocument();
  });

  it("shows a 404 not-found state for a nonexistent endpoint", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);

    renderAuthenticated(<WebhookEndpointDetailPage endpointId={ENDPOINT_ID} />);

    expect(await screen.findByText("Webhook endpoint not found")).toBeInTheDocument();
  });

  it("blocks a foreign workspace's endpoint the same way as a nonexistent one", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedWebhookEndpoints(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeWebhookEndpointFixture({ id: ENDPOINT_ID, name: "Foreign endpoint" }),
    ]);

    renderAuthenticated(<WebhookEndpointDetailPage endpointId={ENDPOINT_ID} />);

    expect(await screen.findByText("Webhook endpoint not found")).toBeInTheDocument();
  });

  it("shows the not-found state for a malformed endpoint ID without ever issuing a request", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);

    renderAuthenticated(<WebhookEndpointDetailPage endpointId="not-a-uuid" />);

    expect(await screen.findByText("Webhook endpoint not found")).toBeInTheDocument();
  });

  it("shows the unrecognized-status fallback label rather than crashing", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedWebhookEndpoints(FIXTURE_WORKSPACE_ACME.id, [
      makeWebhookEndpointFixture({
        id: ENDPOINT_ID,
        name: "Endpoint",
        status: "future_status" as unknown as "active",
      }),
    ]);

    renderAuthenticated(<WebhookEndpointDetailPage endpointId={ENDPOINT_ID} />);

    expect(await screen.findByText("future_status")).toBeInTheDocument();
  });

  it("never renders an edit/rotate/disable control (deferred to a later chunk)", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]); // admin
    seedWebhookEndpoints(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeWebhookEndpointFixture({ id: ENDPOINT_ID, name: "Endpoint" }),
    ]);

    renderAuthenticated(<WebhookEndpointDetailPage endpointId={ENDPOINT_ID} />);

    await screen.findByRole("heading", { name: "Endpoint" });
    expect(screen.queryByRole("button", { name: /rotate/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^edit$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^disable$/i })).not.toBeInTheDocument();
  });
});
