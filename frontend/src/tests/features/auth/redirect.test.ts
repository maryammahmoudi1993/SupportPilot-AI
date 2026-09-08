import { describe, expect, it } from "vitest";

import {
  DEFAULT_REDIRECT_TARGET,
  isSafeRedirectTarget,
  resolveRedirectTarget,
} from "@/features/auth/redirect";

describe("isSafeRedirectTarget", () => {
  it("accepts a simple internal path", () => {
    expect(isSafeRedirectTarget("/app")).toBe(true);
  });

  it("accepts an internal path with a query string", () => {
    expect(isSafeRedirectTarget("/tickets?status=open")).toBe(true);
  });

  it("rejects null/undefined/empty", () => {
    expect(isSafeRedirectTarget(null)).toBe(false);
    expect(isSafeRedirectTarget(undefined)).toBe(false);
    expect(isSafeRedirectTarget("")).toBe(false);
  });

  it("rejects a path that does not start with /", () => {
    expect(isSafeRedirectTarget("app")).toBe(false);
  });

  it("rejects an absolute external URL", () => {
    expect(isSafeRedirectTarget("https://evil.example/phish")).toBe(false);
    expect(isSafeRedirectTarget("http://evil.example")).toBe(false);
  });

  it("rejects a protocol-relative URL", () => {
    expect(isSafeRedirectTarget("//evil.example")).toBe(false);
    expect(isSafeRedirectTarget("///evil.example")).toBe(false);
  });

  it("rejects a backslash variant some browsers normalize to protocol-relative", () => {
    expect(isSafeRedirectTarget("/\\evil.example")).toBe(false);
  });

  it("rejects a javascript: URL", () => {
    expect(isSafeRedirectTarget("javascript:alert(1)")).toBe(false);
  });

  it("rejects a target containing whitespace or control characters", () => {
    expect(isSafeRedirectTarget("/\t/evil.example")).toBe(false);
    expect(isSafeRedirectTarget("/ /evil.example")).toBe(false);
    expect(isSafeRedirectTarget("/\n/evil.example")).toBe(false);
  });

  it("treats a colon-containing path segment as a plain internal path, not a scheme", () => {
    // "/data:text/html,..." starts with "/", so it can only ever resolve as
    // a same-origin pathname (most likely a 404) — never as a data: URI.
    expect(isSafeRedirectTarget("/data:text/html,not-a-real-route")).toBe(true);
  });
});

describe("resolveRedirectTarget", () => {
  it("returns the target when safe", () => {
    expect(resolveRedirectTarget("/app")).toBe("/app");
  });

  it("falls back to the default target when unsafe", () => {
    expect(resolveRedirectTarget("https://evil.example")).toBe(DEFAULT_REDIRECT_TARGET);
    expect(resolveRedirectTarget(null)).toBe(DEFAULT_REDIRECT_TARGET);
  });
});
