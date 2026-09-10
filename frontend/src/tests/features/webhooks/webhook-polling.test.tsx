import { act, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WebhookDeliveryDetailPage } from "@/features/webhooks/components/webhook-delivery-detail-page";
import { WEBHOOK_DELIVERY_POLL_INTERVAL_MS, pollWhileDeliveryNonTerminal } from "@/features/webhooks/queries";
import { isTerminalDeliveryStatus } from "@/features/webhooks/types";
import { FIXTURE_USER, FIXTURE_WORKSPACE_ACME, mockState } from "@/tests/msw/handlers";
import {
  makeWebhookDeliveryFixture,
  seedWebhookDeliveries,
  webhookMockState,
} from "@/tests/msw/webhook-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

const DELIVERY_1 = "11111111-1111-4111-8111-111111111111";

function signIn() {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = [FIXTURE_WORKSPACE_ACME];
}

describe("isTerminalDeliveryStatus / pollWhileDeliveryNonTerminal (pure decision logic)", () => {
  it("classifies delivered/failed/dead as terminal", () => {
    expect(isTerminalDeliveryStatus("delivered")).toBe(true);
    expect(isTerminalDeliveryStatus("failed")).toBe(true);
    expect(isTerminalDeliveryStatus("dead")).toBe(true);
  });

  it("classifies pending/claimed/retry_scheduled as non-terminal", () => {
    expect(isTerminalDeliveryStatus("pending")).toBe(false);
    expect(isTerminalDeliveryStatus("claimed")).toBe(false);
    expect(isTerminalDeliveryStatus("retry_scheduled")).toBe(false);
  });

  it("stops polling once the fetched delivery is terminal", () => {
    expect(pollWhileDeliveryNonTerminal({ state: { data: makeQueryDelivery("delivered") } })).toBe(
      false,
    );
  });

  it("keeps polling at the fixed interval while the delivery is non-terminal", () => {
    expect(pollWhileDeliveryNonTerminal({ state: { data: makeQueryDelivery("pending") } })).toBe(
      WEBHOOK_DELIVERY_POLL_INTERVAL_MS,
    );
  });

  it("does not poll before any data has been fetched yet", () => {
    expect(pollWhileDeliveryNonTerminal({ state: { data: undefined } })).toBe(false);
  });

  function makeQueryDelivery(status: string) {
    return { status } as never;
  }
});

describe("WebhookDeliveryDetailPage polling (integration)", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("keeps re-fetching a non-terminal delivery and stops once it turns terminal", async () => {
    signIn();
    seedWebhookDeliveries(FIXTURE_WORKSPACE_ACME.id, [
      makeWebhookDeliveryFixture({
        delivery_id: DELIVERY_1,
        endpoint_id: "ep-1",
        endpoint_name: "Endpoint",
        status: "retry_scheduled",
        delivered_at: null,
        failed_at: null,
      }),
    ]);

    renderAuthenticated(<WebhookDeliveryDetailPage deliveryId={DELIVERY_1} />);
    expect(await screen.findByText("Still in progress")).toBeInTheDocument();

    const callsAfterInitial = webhookMockState.deliveryDetailCallCount;
    expect(callsAfterInitial).toBe(1);

    // Flip the backend to terminal, then let one more poll interval pass.
    seedWebhookDeliveries(FIXTURE_WORKSPACE_ACME.id, [
      makeWebhookDeliveryFixture({
        delivery_id: DELIVERY_1,
        endpoint_id: "ep-1",
        endpoint_name: "Endpoint",
        status: "delivered",
        delivered_at: "2026-01-01T00:05:00Z",
        failed_at: null,
      }),
    ]);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(WEBHOOK_DELIVERY_POLL_INTERVAL_MS + 100);
    });
    expect(await screen.findByText("Settled")).toBeInTheDocument();
    const callsAfterTerminal = webhookMockState.deliveryDetailCallCount;
    expect(callsAfterTerminal).toBe(2);

    // Advancing well past another interval must not produce a further fetch —
    // the delivery is terminal, so polling has genuinely stopped.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(WEBHOOK_DELIVERY_POLL_INTERVAL_MS * 3);
    });
    expect(webhookMockState.deliveryDetailCallCount).toBe(callsAfterTerminal);
  });
});
