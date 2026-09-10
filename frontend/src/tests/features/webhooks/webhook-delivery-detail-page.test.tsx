import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WebhookDeliveryDetailPage } from "@/features/webhooks/components/webhook-delivery-detail-page";
import { FIXTURE_USER, FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX, mockState } from "@/tests/msw/handlers";
import { makeWebhookDeliveryFixture, seedWebhookDeliveries } from "@/tests/msw/webhook-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

const DELIVERY_ID = "22222222-2222-4222-8222-222222222222";

describe("WebhookDeliveryDetailPage", () => {
  it("renders real safe delivery detail fields for a terminal (delivered) delivery", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedWebhookDeliveries(FIXTURE_WORKSPACE_ACME.id, [
      makeWebhookDeliveryFixture({
        delivery_id: DELIVERY_ID,
        endpoint_id: "ep-1",
        endpoint_name: "Support ops relay",
        event_type: "approval.approved",
        status: "delivered",
        attempt_count: 1,
        max_attempts: 5,
        last_http_status: 200,
        delivered_at: "2026-01-01T00:00:05Z",
        failed_at: null,
      }),
    ]);

    renderAuthenticated(<WebhookDeliveryDetailPage deliveryId={DELIVERY_ID} />);

    expect(await screen.findByRole("heading", { name: "Approval approved" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Support ops relay" })).toHaveAttribute(
      "href",
      "/app/integrations/webhooks/ep-1",
    );
    expect(screen.getByText("Settled")).toBeInTheDocument();
    expect(screen.getByText("1 / 5")).toBeInTheDocument();
    expect(screen.getByText("200")).toBeInTheDocument();
    // A settled delivery never shows a stale "Next attempt" — that field
    // only means anything while non-terminal (see the component's comment).
    expect(screen.queryByText("Next attempt")).not.toBeInTheDocument();
    // At-least-once honesty — never claims exactly-once.
    expect(screen.getByText(/at-least-once, never exactly-once/i)).toBeInTheDocument();
  });

  it("a non-terminal delivery shows 'Still in progress' and a real Next attempt timestamp", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedWebhookDeliveries(FIXTURE_WORKSPACE_ACME.id, [
      makeWebhookDeliveryFixture({
        delivery_id: DELIVERY_ID,
        endpoint_id: "ep-1",
        endpoint_name: "Endpoint",
        status: "retry_scheduled",
        attempt_count: 1,
        max_attempts: 5,
        next_attempt_at: "2026-01-01T00:05:00Z",
        delivered_at: null,
        failed_at: null,
      }),
    ]);

    renderAuthenticated(<WebhookDeliveryDetailPage deliveryId={DELIVERY_ID} />);

    expect(await screen.findByText("Still in progress")).toBeInTheDocument();
    expect(screen.getByText("Next attempt")).toBeInTheDocument();
  });

  it("a dead (terminal, non-retryable) delivery renders its real safe error code, never a raw payload", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedWebhookDeliveries(FIXTURE_WORKSPACE_ACME.id, [
      makeWebhookDeliveryFixture({
        delivery_id: DELIVERY_ID,
        endpoint_id: "ep-1",
        endpoint_name: "Endpoint",
        status: "dead",
        last_error_code: "webhook_invalid_url",
        last_http_status: null,
      }),
    ]);

    renderAuthenticated(<WebhookDeliveryDetailPage deliveryId={DELIVERY_ID} />);

    await screen.findByText("Dead");
    expect(screen.getByText("webhook_invalid_url")).toBeInTheDocument();
    // No request payload or response body is ever exposed by the real
    // serializer — nothing here to render, and nothing fabricated either.
    expect(document.body.innerHTML).not.toMatch(/response_body|request_payload/i);
  });

  it("shows the unrecognized-status fallback label rather than crashing", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedWebhookDeliveries(FIXTURE_WORKSPACE_ACME.id, [
      makeWebhookDeliveryFixture({
        delivery_id: DELIVERY_ID,
        endpoint_id: "ep-1",
        endpoint_name: "Endpoint",
        status: "future_status",
      }),
    ]);

    renderAuthenticated(<WebhookDeliveryDetailPage deliveryId={DELIVERY_ID} />);

    expect(await screen.findByText("future_status")).toBeInTheDocument();
  });

  it("shows a 404 not-found state for a nonexistent delivery", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);

    renderAuthenticated(<WebhookDeliveryDetailPage deliveryId={DELIVERY_ID} />);

    expect(await screen.findByText("Webhook delivery not found")).toBeInTheDocument();
  });

  it("blocks a foreign workspace's delivery the same way as a nonexistent one", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedWebhookDeliveries(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeWebhookDeliveryFixture({
        delivery_id: DELIVERY_ID,
        endpoint_id: "ep-1",
        endpoint_name: "Foreign endpoint",
      }),
    ]);

    renderAuthenticated(<WebhookDeliveryDetailPage deliveryId={DELIVERY_ID} />);

    expect(await screen.findByText("Webhook delivery not found")).toBeInTheDocument();
  });

  it("shows the not-found state for a malformed delivery ID without ever issuing a request", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);

    renderAuthenticated(<WebhookDeliveryDetailPage deliveryId="not-a-uuid" />);

    expect(await screen.findByText("Webhook delivery not found")).toBeInTheDocument();
  });

  it("never renders a redrive control (deferred to a later chunk)", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]); // admin
    seedWebhookDeliveries(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeWebhookDeliveryFixture({
        delivery_id: DELIVERY_ID,
        endpoint_id: "ep-1",
        endpoint_name: "Endpoint",
        status: "failed",
      }),
    ]);

    renderAuthenticated(<WebhookDeliveryDetailPage deliveryId={DELIVERY_ID} />);

    await screen.findByText("Failed");
    expect(screen.queryByRole("button", { name: /redrive/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^retry$/i })).not.toBeInTheDocument();
  });
});
