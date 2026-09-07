import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/errors";
import { unwrap, withRequestTimeout } from "@/lib/api/request";

function fakeResponse(status: number) {
  return new Response(null, { status });
}

describe("unwrap", () => {
  it("returns data on a successful result", async () => {
    const result = await unwrap(
      Promise.resolve({ data: { id: "1" }, error: undefined, response: fakeResponse(200) }),
    );
    expect(result).toEqual({ id: "1" });
  });

  it("throws a normalized ApiError when the result carries an error envelope", async () => {
    await expect(
      unwrap(
        Promise.resolve({
          data: undefined,
          error: { error: { code: "not_found", message: "Not found." } },
          response: fakeResponse(404),
        }),
      ),
    ).rejects.toMatchObject({ code: "not_found", status: 404 });
  });

  it("throws a normalized ApiError when the underlying fetch rejects", async () => {
    await expect(unwrap(Promise.reject(new TypeError("Failed to fetch")))).rejects.toBeInstanceOf(
      ApiError,
    );
  });

  it("throws a parse_error when data and error are both absent", async () => {
    await expect(
      unwrap(Promise.resolve({ data: undefined, error: undefined, response: fakeResponse(204) })),
    ).rejects.toMatchObject({ code: "parse_error" });
  });
});

describe("withRequestTimeout", () => {
  it("resolves with the callback's result and disposes the timer", async () => {
    const result = await withRequestTimeout(async (signal) => {
      expect(signal.aborted).toBe(false);
      return "ok";
    }, 1000);
    expect(result).toBe("ok");
  });

  it("propagates a thrown error from the callback", async () => {
    await expect(
      withRequestTimeout(async () => {
        throw new ApiError("boom", { code: "unknown_error", status: null });
      }, 1000),
    ).rejects.toThrow("boom");
  });
});
