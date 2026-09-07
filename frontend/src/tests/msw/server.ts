import { setupServer } from "msw/node";

import { authHandlers } from "@/tests/msw/handlers";

export const server = setupServer(...authHandlers);
