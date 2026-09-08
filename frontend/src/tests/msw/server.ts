import { setupServer } from "msw/node";

import { authHandlers } from "@/tests/msw/handlers";
import { customerHandlers } from "@/tests/msw/customer-handlers";
import { conversationHandlers } from "@/tests/msw/conversation-handlers";

export const server = setupServer(...authHandlers, ...customerHandlers, ...conversationHandlers);
