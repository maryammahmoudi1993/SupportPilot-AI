import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ConversationHandoffSection } from "@/features/handoffs/components/conversation-handoff-section";
import { makeHandoffFixture, seedHandoffs } from "@/tests/msw/handoff-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

const CONV_1 = "22222222-2222-4222-8222-222222222222";
const CONV_2 = "33333333-3333-4333-8333-333333333333";

describe("ConversationHandoffSection", () => {
  it("renders only the handoffs whose real conversation filter matches this conversation", async () => {
    seedHandoffs("ws-1", [
      makeHandoffFixture({ id: "h-1", conversation_id: CONV_1, reason_code: "customer_requested" }),
      makeHandoffFixture({ id: "h-2", conversation_id: CONV_2, reason_code: "low_confidence" }),
    ]);

    renderAuthenticated(<ConversationHandoffSection workspaceId="ws-1" conversationId={CONV_1} />);

    expect(await screen.findByText("Customer requested a human")).toBeInTheDocument();
    expect(screen.queryByText("Low-confidence retrieval/response")).not.toBeInTheDocument();
  });

  it("shows an honest empty state when a conversation has no handoff", async () => {
    seedHandoffs("ws-1", []);

    renderAuthenticated(<ConversationHandoffSection workspaceId="ws-1" conversationId={CONV_1} />);

    expect(await screen.findByText("No human handoff for this conversation.")).toBeInTheDocument();
  });

  it("shows the real assignee when a handoff is assigned", async () => {
    seedHandoffs("ws-1", [
      makeHandoffFixture({
        id: "h-1",
        conversation_id: CONV_1,
        status: "assigned",
        assigned_to: { id: "m-1", email: "manager@example.com", role: "support_manager" },
      }),
    ]);

    renderAuthenticated(<ConversationHandoffSection workspaceId="ws-1" conversationId={CONV_1} />);

    expect(await screen.findByText(/Assigned to manager@example.com/)).toBeInTheDocument();
  });
});
