import { setupServer } from "msw/node";

import { agentRunHandlers } from "@/tests/msw/agent-run-handlers";
import { approvalHandlers } from "@/tests/msw/approval-handlers";
import { authHandlers } from "@/tests/msw/handlers";
import { customerHandlers } from "@/tests/msw/customer-handlers";
import { conversationHandlers } from "@/tests/msw/conversation-handlers";
import { handoffHandlers } from "@/tests/msw/handoff-handlers";
import { knowledgeHandlers } from "@/tests/msw/knowledge-handlers";
import { ticketHandlers } from "@/tests/msw/ticket-handlers";
import { toolExecutionHandlers } from "@/tests/msw/tool-execution-handlers";

export const server = setupServer(
  ...authHandlers,
  ...customerHandlers,
  ...conversationHandlers,
  ...ticketHandlers,
  ...agentRunHandlers,
  ...toolExecutionHandlers,
  ...approvalHandlers,
  ...handoffHandlers,
  ...knowledgeHandlers,
);
