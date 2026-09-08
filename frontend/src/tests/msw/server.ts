import { setupServer } from "msw/node";

import { authHandlers } from "@/tests/msw/handlers";
import { customerHandlers } from "@/tests/msw/customer-handlers";

export const server = setupServer(...authHandlers, ...customerHandlers);
