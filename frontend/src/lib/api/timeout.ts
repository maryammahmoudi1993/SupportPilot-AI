/**
 * Combine a caller-supplied AbortSignal with a request timeout, without
 * relying on `AbortSignal.any` (not available on all browsers this app
 * still supports). Returns the combined signal plus a `dispose` function
 * the caller must invoke once the request settles, to clear the timer and
 * detach listeners.
 */
export function withTimeout(
  timeoutMs: number,
  callerSignal?: AbortSignal,
): { signal: AbortSignal; dispose: () => void } {
  const controller = new AbortController();

  const onCallerAbort = () => controller.abort(callerSignal?.reason);
  if (callerSignal) {
    if (callerSignal.aborted) {
      controller.abort(callerSignal.reason);
    } else {
      callerSignal.addEventListener("abort", onCallerAbort);
    }
  }

  const timer = setTimeout(() => {
    controller.abort(new DOMException("Request timed out", "AbortError"));
  }, timeoutMs);

  const dispose = () => {
    clearTimeout(timer);
    callerSignal?.removeEventListener("abort", onCallerAbort);
  };

  return { signal: controller.signal, dispose };
}
