import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { describe, expect, it, vi } from "vitest";

import { ConversationDetailPage } from "@/features/conversations/components/conversation-detail-page";
import { FIXTURE_USER, FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX, mockState } from "@/tests/msw/handlers";
import {
  conversationMockState,
  makeConversationFixture,
  makeMessageFixture,
  seedConversations,
  seedMessages,
} from "@/tests/msw/conversation-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(),
  usePathname: vi.fn(),
  useSearchParams: vi.fn(),
}));

const CONV_1 = "11111111-1111-4111-8111-111111111111";
const GLOBEX_CONV = "22222222-2222-4222-8222-222222222222";
const CUSTOMER_1 = "33333333-3333-4333-8333-333333333333";

function setupNavigationMocks() {
  const replace = vi.fn();
  vi.mocked(useRouter).mockReturnValue({ replace } as unknown as ReturnType<typeof useRouter>);
  vi.mocked(usePathname).mockReturnValue(`/app/inbox/${CONV_1}`);
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams() as unknown as ReturnType<typeof useSearchParams>,
  );
  return { replace };
}

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

describe("ConversationDetailPage", () => {
  it("renders real conversation fields, customer link, and the message timeline in server order", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    setupNavigationMocks();
    seedConversations(FIXTURE_WORKSPACE_ACME.id, [
      makeConversationFixture({
        id: CONV_1,
        customer_id: CUSTOMER_1,
        subject: "Refund question",
        status: "pending",
        channel: "chat",
        assigned_to: { id: "m1", email: "agent@example.com", role: "support_agent" },
      }),
    ]);
    seedMessages(CONV_1, [
      makeMessageFixture({
        id: "msg-1",
        sender_type: "customer",
        direction: "inbound",
        body: "First (same instant)",
        created_at: "2026-01-01T00:00:00Z",
      }),
      // Same `created_at` as msg-1 — a client-side re-sort by timestamp
      // alone could legally reorder these two; the component must not.
      makeMessageFixture({
        id: "msg-2",
        sender_type: "human_agent",
        direction: "outbound",
        body: "Second (same instant)",
        sender: { id: "m1", email: "agent@example.com", role: "support_agent" },
        created_at: "2026-01-01T00:00:00Z",
      }),
      makeMessageFixture({
        id: "msg-3",
        sender_type: "ai_agent",
        direction: "outbound",
        body: "Third, from the agent",
        created_at: "2026-01-01T00:05:00Z",
      }),
      makeMessageFixture({
        id: "msg-4",
        sender_type: "system",
        direction: "internal",
        body: "Fourth, an internal note",
        created_at: "2026-01-01T00:06:00Z",
      }),
    ]);

    renderAuthenticated(<ConversationDetailPage conversationId={CONV_1} />);

    expect(await screen.findByRole("heading", { name: "Refund question" })).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(screen.getByText("Chat")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: `Customer #${CUSTOMER_1.slice(0, 8)}` })).toHaveAttribute(
      "href",
      `/app/customers/${CUSTOMER_1}`,
    );
    // Appears twice: once as the conversation's "Assigned to" field, once
    // as msg-2's sender label (the same real agent sent that message).
    expect(screen.getAllByText("agent@example.com")).toHaveLength(2);

    // Server order preserved exactly, not re-sorted client-side.
    const items = screen.getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      expect.stringContaining("First (same instant)"),
      expect.stringContaining("Second (same instant)"),
      expect.stringContaining("Third, from the agent"),
      expect.stringContaining("Fourth, an internal note"),
    ]);

    // Sender/source semantics: customer, named agent, AI agent, system + internal-note marker.
    const timeline = screen.getByRole("list");
    expect(within(timeline).getByText("Customer")).toBeInTheDocument();
    expect(within(timeline).getByText("AI agent")).toBeInTheDocument();
    expect(within(timeline).getByText("System")).toBeInTheDocument();
    expect(within(timeline).getByText("Internal note")).toBeInTheDocument();
  });

  it("wraps long unbroken content safely without dangerouslySetInnerHTML", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    setupNavigationMocks();
    seedConversations(FIXTURE_WORKSPACE_ACME.id, [
      makeConversationFixture({ id: CONV_1, customer_id: CUSTOMER_1, subject: "Long content" }),
    ]);
    const longUrl = `https://example.com/${"a".repeat(300)}`;
    seedMessages(CONV_1, [
      makeMessageFixture({
        id: "msg-1",
        sender_type: "customer",
        direction: "inbound",
        body: `Check this out: ${longUrl}\nSecond line.`,
      }),
    ]);

    renderAuthenticated(<ConversationDetailPage conversationId={CONV_1} />);

    const bodyText = await screen.findByText((content) => content.includes(longUrl));
    expect(bodyText.tagName).toBe("P");
    expect(bodyText.className).toContain("break-words");
    expect(bodyText.className).toContain("whitespace-pre-wrap");
  });

  it("shows a safe not-found state for a confirmed 404", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    setupNavigationMocks();

    renderAuthenticated(<ConversationDetailPage conversationId="00000000-0000-4000-8000-000000000000" />);

    expect(await screen.findByText("Conversation not found")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Inbox" })).toHaveAttribute("href", "/app/inbox");
  });

  it("shows a safe not-found state for a conversation belonging to a different workspace — never leaked", async () => {
    signIn([FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX]);
    setupNavigationMocks();
    seedConversations(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeConversationFixture({
        id: GLOBEX_CONV,
        customer_id: CUSTOMER_1,
        subject: "Globex Only Conversation",
      }),
    ]);
    seedMessages(GLOBEX_CONV, [
      makeMessageFixture({ id: "m1", sender_type: "customer", direction: "inbound", body: "hi" }),
    ]);
    // Active workspace defaults to Acme; the conversation above belongs to Globex.

    renderAuthenticated(<ConversationDetailPage conversationId={GLOBEX_CONV} />);

    expect(await screen.findByText("Conversation not found")).toBeInTheDocument();
    expect(screen.queryByText("Globex Only Conversation")).not.toBeInTheDocument();
    expect(screen.queryByText("hi")).not.toBeInTheDocument();
  });

  it("rejects a malformed route ID without ever making a network request", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    setupNavigationMocks();
    conversationMockState.detailNetworkError = true; // would fail loudly if a request were made

    renderAuthenticated(<ConversationDetailPage conversationId="not-a-uuid" />);

    expect(await screen.findByText("Conversation not found")).toBeInTheDocument();
  });

  it("shows a network-error state (not not-found) and recovers via Retry", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    setupNavigationMocks();
    conversationMockState.detailNetworkError = true;

    renderAuthenticated(<ConversationDetailPage conversationId={CONV_1} />);

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
    expect(screen.queryByText("Conversation not found")).not.toBeInTheDocument();

    conversationMockState.detailNetworkError = false;
    seedConversations(FIXTURE_WORKSPACE_ACME.id, [
      makeConversationFixture({ id: CONV_1, customer_id: CUSTOMER_1, subject: "Recovered" }),
    ]);
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("heading", { name: "Recovered" })).toBeInTheDocument();
  });

  it("shows an empty state for a conversation with zero messages, distinct from a loading/error state", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    setupNavigationMocks();
    seedConversations(FIXTURE_WORKSPACE_ACME.id, [
      makeConversationFixture({ id: CONV_1, customer_id: CUSTOMER_1, subject: "Empty" }),
    ]);

    renderAuthenticated(<ConversationDetailPage conversationId={CONV_1} />);

    expect(await screen.findByText("No messages in this conversation yet.")).toBeInTheDocument();
  });
});
