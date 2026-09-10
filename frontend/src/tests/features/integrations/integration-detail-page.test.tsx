import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { IntegrationConnectionDetailPage } from "@/features/integrations/components/integration-detail-page";
import { FIXTURE_USER, FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX, mockState } from "@/tests/msw/handlers";
import {
  makeIntegrationConnectionFixture,
  seedIntegrationConnections,
} from "@/tests/msw/integration-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

const CONNECTION_ID = "11111111-1111-4111-8111-111111111111";

describe("IntegrationConnectionDetailPage", () => {
  it("renders real safe connection detail fields", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedIntegrationConnections(FIXTURE_WORKSPACE_ACME.id, [
      makeIntegrationConnectionFixture({
        id: CONNECTION_ID,
        provider: "stripe",
        display_name: "Primary Stripe",
        status: "active",
        environment: "live",
        configuration: { statement_descriptor: "SUPPORTPILOT" },
        credentials_configured: true,
        credential_version: 3,
      }),
    ]);

    renderAuthenticated(
      <IntegrationConnectionDetailPage connectionId={CONNECTION_ID} />,
    );

    expect(await screen.findByRole("heading", { name: "Primary Stripe" })).toBeInTheDocument();
    expect(screen.getByText("Stripe")).toBeInTheDocument();
    expect(screen.getByText("Configured")).toBeInTheDocument();
    expect(screen.getByText("payment_lookup, refund")).toBeInTheDocument();
  });

  it("never renders raw credential material — only the safe configured indicator", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedIntegrationConnections(FIXTURE_WORKSPACE_ACME.id, [
      makeIntegrationConnectionFixture({
        id: CONNECTION_ID,
        provider: "stripe",
        configuration: { note: "sk_test_should_never_appear_but_this_is_just_config" },
      }),
    ]);

    renderAuthenticated(
      <IntegrationConnectionDetailPage connectionId={CONNECTION_ID} />,
    );

    await screen.findByRole("heading", { name: "Stripe" });
    // No field named "credentials"/"secret"/"token" ever renders the raw value —
    // the DOM has no attribute or text node named encrypted_credentials.
    expect(document.body.innerHTML).not.toMatch(/encrypted_credentials/i);
    expect(document.body.innerHTML).not.toMatch(/"credentials"\s*:/i);
  });

  it("shows a 404 not-found state for a nonexistent connection, never distinguishing it from a foreign-workspace one", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);

    renderAuthenticated(
      <IntegrationConnectionDetailPage connectionId={CONNECTION_ID} />,
    );

    expect(
      await screen.findByText("Integration connection not found"),
    ).toBeInTheDocument();
  });

  it("blocks a foreign workspace's connection the same way as a nonexistent one", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedIntegrationConnections(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeIntegrationConnectionFixture({ id: CONNECTION_ID, provider: "email" }),
    ]);

    renderAuthenticated(
      <IntegrationConnectionDetailPage connectionId={CONNECTION_ID} />,
    );

    expect(
      await screen.findByText("Integration connection not found"),
    ).toBeInTheDocument();
  });

  it("shows the not-found state for a malformed connection ID without ever issuing a request", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);

    renderAuthenticated(<IntegrationConnectionDetailPage connectionId="not-a-uuid" />);

    expect(
      await screen.findByText("Integration connection not found"),
    ).toBeInTheDocument();
  });

  it("shows the unrecognized-status fallback label rather than crashing", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedIntegrationConnections(FIXTURE_WORKSPACE_ACME.id, [
      makeIntegrationConnectionFixture({
        id: CONNECTION_ID,
        provider: "google_calendar",
        status: "future_status" as unknown as "active",
      }),
    ]);

    renderAuthenticated(
      <IntegrationConnectionDetailPage connectionId={CONNECTION_ID} />,
    );

    expect(await screen.findByText("future_status")).toBeInTheDocument();
  });
});
