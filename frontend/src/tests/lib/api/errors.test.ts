import { describe, expect, it } from "vitest";

import { normalizeHttpError, normalizeTransportError } from "@/lib/api/errors";

describe("normalizeHttpError", () => {
  it("maps a well-formed backend envelope to a typed ApiError", () => {
    const err = normalizeHttpError(404, {
      error: { code: "not_found", message: "Customer not found." },
    });
    expect(err.code).toBe("not_found");
    expect(err.status).toBe(404);
    expect(err.message).toBe("Customer not found.");
    expect(err.details).toBeUndefined();
  });

  it("preserves the details field for validation errors", () => {
    const err = normalizeHttpError(400, {
      error: {
        code: "validation_error",
        message: "Invalid request.",
        details: { email: ["This field is required."] },
      },
    });
    expect(err.code).toBe("validation_error");
    expect(err.details).toEqual({ email: ["This field is required."] });
  });

  it("falls back to unknown_error for an unrecognized code, without dropping the message", () => {
    const err = normalizeHttpError(400, {
      error: { code: "some_future_code", message: "Something new." },
    });
    expect(err.code).toBe("unknown_error");
    expect(err.message).toBe("Something new.");
  });

  it("falls back to a safe parse_error for a non-envelope body", () => {
    const err = normalizeHttpError(502, "<html>Bad Gateway</html>");
    expect(err.code).toBe("parse_error");
    expect(err.status).toBe(502);
    expect(err.message).not.toContain("<html>");
  });

  it("falls back to a safe parse_error for a null body", () => {
    const err = normalizeHttpError(500, null);
    expect(err.code).toBe("parse_error");
  });
});

describe("normalizeTransportError", () => {
  it("maps an AbortError to a timeout ApiError", () => {
    const err = normalizeTransportError(new DOMException("aborted", "AbortError"));
    expect(err.code).toBe("timeout");
    expect(err.status).toBeNull();
  });

  it("maps any other failure to a network_error ApiError", () => {
    const err = normalizeTransportError(new TypeError("Failed to fetch"));
    expect(err.code).toBe("network_error");
    expect(err.status).toBeNull();
  });
});
