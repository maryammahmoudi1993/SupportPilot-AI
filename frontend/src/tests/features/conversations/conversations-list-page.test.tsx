import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { describe, expect, it, vi } from "vitest";

import { ConversationsListPage } from "@/features/conversations/components/conversations-list-page";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { FIXTURE_USER, FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX, mockState } from "@/tests/msw/handlers";
import {
  conversationMockState,
  makeConversationFixture,
  seedConversations,
} from "@/tests/msw/conversation-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(),
  usePathname: vi.fn(),
  useSearchParams: vi.fn(),
}));

function setupNavigationMocks(initialQuery = "") {
  const replace = vi.fn();
  vi.mocked(useRouter).mockReturnValue({ replace } as unknown as ReturnType<typeof useRouter>);
  vi.mocked(usePathname).mockReturnValue("/app/inbox");
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams(initialQuery) as unknown as ReturnType<typeof useSearchParams>,
  );
  return { replace };
}

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

const CUSTOMER_1 = "11111111-1111-4111-8111-111111111111";

describe("ConversationsListPage", () => {
  it("renders real conversation rows returned by the API", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedConversations(FIXTURE_WORKSPACE_ACME.id, [
      makeConversationFixture({
        id: "conv-1",
        customer_id: CUSTOMER_1,
        subject: "Refund question",
        status: "open",
        channel: "email",
      }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<ConversationsListPage />);

    expect(await screen.findByRole("link", { name: "Refund question" })).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByText("Open")).toBeInTheDocument();
    expect(within(table).getByText("Email")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: `Customer #${CUSTOMER_1.slice(0, 8)}` })).toHaveAttribute(
      "href",
      `/app/customers/${CUSTOMER_1}`,
    );
  });

  it("shows a distinct empty state for zero conversations", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    setupNavigationMocks();

    renderAuthenticated(<ConversationsListPage />);

    expect(await screen.findByText("No conversations yet")).toBeInTheDocument();
  });

  it("shows a network-error state (not empty) and recovers via Retry", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    conversationMockState.listNetworkError = true;
    setupNavigationMocks();

    renderAuthenticated(<ConversationsListPage />);

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
    expect(screen.queryByText("No conversations yet")).not.toBeInTheDocument();

    conversationMockState.listNetworkError = false;
    seedConversations(FIXTURE_WORKSPACE_ACME.id, [
      makeConversationFixture({ id: "conv-1", customer_id: CUSTOMER_1, subject: "Recovered" }),
    ]);
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("link", { name: "Recovered" })).toBeInTheDocument();
  });

  it("pushes a status filter change into the URL with the page reset to 1", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    const { replace } = setupNavigationMocks("page=3");

    renderAuthenticated(<ConversationsListPage />);
    await screen.findByText("No conversations yet");

    await userEvent.setup().selectOptions(screen.getByLabelText("Status"), "open");

    expect(replace).toHaveBeenCalledWith("/app/inbox?status=open", { scroll: false });
  });

  it("paginates using the backend's next/previous contract and preserves filters", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedConversations(
      FIXTURE_WORKSPACE_ACME.id,
      Array.from({ length: 55 }, (_, index) =>
        makeConversationFixture({
          id: `conv-${index}`,
          customer_id: CUSTOMER_1,
          subject: `Conversation ${index}`,
          status: "open",
        }),
      ),
    );
    const { replace } = setupNavigationMocks("status=open");

    renderAuthenticated(<ConversationsListPage />);

    const nextButton = await screen.findByRole("button", { name: "Next page" });
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    expect(nextButton).toBeEnabled();

    await userEvent.setup().click(nextButton);

    expect(replace).toHaveBeenCalledWith("/app/inbox?page=2&status=open", { scroll: false });
  });

  it("renders an unrecognized future channel/status value safely instead of crashing", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);
    seedConversations(FIXTURE_WORKSPACE_ACME.id, [
      makeConversationFixture({
        id: "conv-1",
        customer_id: CUSTOMER_1,
        subject: "Future channel",
        // Cast through the fixture's loose typing to simulate a backend
        // enum value newer than this frontend build knows about.
        status: "escalated" as never,
        channel: "voice" as never,
      }),
    ]);
    setupNavigationMocks();

    renderAuthenticated(<ConversationsListPage />);

    expect(await screen.findByRole("link", { name: "Future channel" })).toBeInTheDocument();
    // Falls back to the raw enum value as its own label rather than crashing.
    expect(screen.getByText("escalated")).toBeInTheDocument();
    expect(screen.getByText("voice")).toBeInTheDocument();
  });

  it("never renders another workspace's conversations while/after switching workspaces", async () => {
    signIn([FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX]);
    seedConversations(FIXTURE_WORKSPACE_ACME.id, [
      makeConversationFixture({ id: "acme-conv", customer_id: CUSTOMER_1, subject: "Acme Conversation" }),
    ]);
    seedConversations(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeConversationFixture({
        id: "globex-conv",
        customer_id: CUSTOMER_1,
        subject: "Globex Conversation",
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
          <ConversationsListPage />
        </>
      );
    }

    renderAuthenticated(<Harness />);

    expect(await screen.findByRole("link", { name: "Acme Conversation" })).toBeInTheDocument();

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: `switch-to-${FIXTURE_WORKSPACE_GLOBEX.name}` }));

    await waitFor(() => expect(screen.queryByText("Acme Conversation")).not.toBeInTheDocument());
    expect(await screen.findByRole("link", { name: "Globex Conversation" })).toBeInTheDocument();
    expect(screen.queryByText("Acme Conversation")).not.toBeInTheDocument();
  });
});
