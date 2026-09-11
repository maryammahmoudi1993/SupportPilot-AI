import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { WebhookDeliveryDetailPage } from "@/features/webhooks/components/webhook-delivery-detail-page";
import { FIXTURE_USER, FIXTURE_WORKSPACE_GLOBEX, mockState } from "@/tests/msw/handlers";
import {
  makeWebhookDeliveryFixture,
  seedWebhookDeliveries,
  webhookMockState,
} from "@/tests/msw/webhook-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

const DELIVERY_ID = "33333333-3333-4333-8333-333333333333";

/**
 * Component-level proof of the redrive success path (Phase 22 Chunk 3,
 * master prompt Part F §27's documented safety limitation): the real
 * backend always schedules a genuine Celery dispatch on a successful
 * redrive (`webhooks/services.py redrive_webhook_delivery`'s
 * `transaction.on_commit`), which this repository has no safe,
 * non-internet transport for — so success is proven here, against a
 * mocked response, never against the real backend.
 */
describe("RedriveDeliveryControl (Phase 22 Chunk 3)", () => {
  it("requires an explicit, honest confirmation before redriving — never claims 'safe' or 'exactly once'", async () => {
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

    await userEvent.setup().click(screen.getByRole("button", { name: /redrive delivery/i }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/at-least-once/i);
    expect(dialog).not.toHaveTextContent(/safe retry/i);
    expect(dialog).not.toHaveTextContent(/exactly once/i);
    expect(dialog).not.toHaveTextContent(/will not duplicate/i);
  });

  it("on a confirmed successful redrive: shows real queued confirmation, refetches the delivery, and hides the button once no longer redrivable", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
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

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /redrive delivery/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^redrive delivery$/i }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(await screen.findByText("Delivery queued for another attempt.")).toBeInTheDocument();
    // The mocked redrive transitions the delivery to `pending` — no longer
    // eligible, so the button itself disappears, while the success message
    // (this component instance never unmounted) stays visible.
    expect(await screen.findByText("Pending")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /redrive delivery/i })).not.toBeInTheDocument();
  });

  it("blocks a duplicate submit while the redrive request is pending (mutation retry: 0)", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedWebhookDeliveries(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeWebhookDeliveryFixture({
        delivery_id: DELIVERY_ID,
        endpoint_id: "ep-1",
        endpoint_name: "Endpoint",
        status: "failed",
      }),
    ]);
    webhookMockState.redriveDelayMs = 200;

    renderAuthenticated(<WebhookDeliveryDetailPage deliveryId={DELIVERY_ID} />);
    await screen.findByText("Failed");

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /redrive delivery/i }));
    const dialog = await screen.findByRole("dialog");
    const confirmButton = within(dialog).getByRole("button", { name: /^redrive delivery$/i });
    await user.click(confirmButton);

    // The dialog's own confirm button is disabled while the request is
    // genuinely still in flight (the mocked handler is held open above).
    await waitFor(() => expect(confirmButton).toBeDisabled());
  });

  it("shows the real server rejection on an invalid-state redrive, never a fabricated success", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedWebhookDeliveries(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeWebhookDeliveryFixture({
        delivery_id: DELIVERY_ID,
        endpoint_id: "ep-1",
        endpoint_name: "Endpoint",
        status: "failed",
      }),
    ]);
    webhookMockState.mutationError = {
      code: "webhook_delivery_not_redrivable",
      message: "This delivery cannot be redriven in its current state.",
      status: 409,
    };

    renderAuthenticated(<WebhookDeliveryDetailPage deliveryId={DELIVERY_ID} />);
    await screen.findByText("Failed");

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /redrive delivery/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^redrive delivery$/i }));

    expect(
      await screen.findByText("This delivery cannot be redriven in its current state."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Delivery queued for another attempt.")).not.toBeInTheDocument();
  });
});
