import { describe, expect, it, vi } from "vitest";

import { withTimeout } from "@/lib/api/timeout";

describe("withTimeout", () => {
  it("aborts the returned signal after the timeout elapses", async () => {
    vi.useFakeTimers();
    const { signal, dispose } = withTimeout(1000);
    expect(signal.aborted).toBe(false);

    vi.advanceTimersByTime(1000);
    expect(signal.aborted).toBe(true);

    dispose();
    vi.useRealTimers();
  });

  it("propagates an abort from the caller-supplied signal", () => {
    const callerController = new AbortController();
    const { signal, dispose } = withTimeout(60_000, callerController.signal);

    callerController.abort();
    expect(signal.aborted).toBe(true);

    dispose();
  });

  it("does not abort before dispose is called and the timer is cleared", () => {
    vi.useFakeTimers();
    const { signal, dispose } = withTimeout(5000);
    dispose();
    vi.advanceTimersByTime(5000);
    expect(signal.aborted).toBe(false);
    vi.useRealTimers();
  });
});
