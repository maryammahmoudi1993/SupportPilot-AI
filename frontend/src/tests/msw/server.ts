import { setupServer } from "msw/node";

import { agentRunHandlers } from "@/tests/msw/agent-run-handlers";
import { authHandlers } from "@/tests/msw/handlers";
import { customerHandlers } from "@/tests/msw/customer-handlers";
import { conversationHandlers } from "@/tests/msw/conversation-handlers";
import { ticketHandlers } from "@/tests/msw/ticket-handlers";

export const server = setupServer(
  ...authHandlers,
  ...customerHandlers,
  ...conversationHandlers,
  ...ticketHandlers,
  ...agentRunHandlers,
);
