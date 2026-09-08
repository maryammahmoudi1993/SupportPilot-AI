import { describe, expect, it } from "vitest";

import { ensureCsrfCookie } from "@/lib/api/csrf";
import { __setTimeoutOverrideForTests } from "@/lib/api/request";
import { mockState } from "@/tests/msw/handlers";

describe("ensureCsrfCookie", () => {
  it("D. bounds a hung CSRF-priming request — a real, abort-driven timeout, not an indefinite wait", async () => {
    __setTimeoutOverrideForTests(50);
    mockState.csrfHang = true;

    await expect(ensureCsrfCookie()).rejects.toMatchObject({ code: "timeout" });
  });
});
