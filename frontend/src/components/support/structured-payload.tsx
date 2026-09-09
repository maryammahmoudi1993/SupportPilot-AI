/**
 * A safe, collapsible viewer for an arbitrary backend-supplied JSON value —
 * shared by every domain that renders a redacted/safe payload (AgentStep's
 * `safe_metadata`, ToolExecution's `arguments_redacted`/`result_redacted`).
 *
 * These payloads are untrusted data (master prompt Part D §13, §15-16):
 * customer-supplied text, external provider responses, or prompt-injection
 * strings may all appear inside them. This component never interprets that
 * content — `JSON.stringify` produces plain text, rendered as a React text
 * node (never `dangerouslySetInnerHTML`, `eval`, or `new Function`), and no
 * key or string value is ever auto-linked or merged into any application
 * object (there is nothing here for a `__proto__`-shaped key to pollute).
 *
 * Bounded presentation: a fixed max-height, independently `overflow-auto`
 * box so a large/deep value scrolls in place rather than stretching page
 * layout or forcing horizontal overflow, plus a defensive hard truncation
 * for a pathologically large serialized payload (backend request/response
 * bodies are already size-capped — see agents/serializers.py
 * MAX_METADATA_BYTES and tools/contracts.py's per-tool input/output models —
 * so this is a last-resort guard, not the primary size control). A native
 * `<details>`/`<summary>` disclosure gives correct keyboard/AT semantics
 * (implicit button role, native expanded state) for free, rather than
 * hand-rolling `aria-expanded`/`aria-controls` on a synthetic toggle.
 */
const MAX_SERIALIZED_LENGTH = 20_000;

function isEmptyValue(value: unknown): boolean {
  return (
    value === null ||
    value === undefined ||
    (typeof value === "object" && !Array.isArray(value) && Object.keys(value).length === 0)
  );
}

export function StructuredPayload({
  value,
  emptyLabel = "—",
  label,
  defaultOpen = true,
}: {
  value: unknown;
  emptyLabel?: string;
  label?: string;
  defaultOpen?: boolean;
}) {
  if (isEmptyValue(value)) {
    return <span className="text-text-secondary text-xs">{emptyLabel}</span>;
  }

  let serialized: string;
  try {
    serialized = JSON.stringify(value, null, 2) ?? String(value);
  } catch {
    // A value JSON.stringify cannot serialize (e.g. a circular structure) —
    // never let a malformed payload crash the page.
    serialized = "(unable to display this value)";
  }
  const truncated = serialized.length > MAX_SERIALIZED_LENGTH;
  const displayed = truncated ? serialized.slice(0, MAX_SERIALIZED_LENGTH) : serialized;

  return (
    <details open={defaultOpen} className="group">
      <summary className="text-text-secondary hover:text-text-primary cursor-pointer text-xs font-medium select-none">
        {label ?? "View details"}
      </summary>
      <pre className="bg-surface-2 border-border-subtle mt-1 max-h-64 overflow-auto rounded-md border p-2 text-xs break-words whitespace-pre-wrap">
        {displayed}
        {truncated && "\n… (truncated)"}
      </pre>
    </details>
  );
}
