/**
 * Renders a backend ISO-8601 timestamp as a semantic `<time>` element with a
 * locale-formatted, human-readable label. Shared across every operational
 * domain (customers now; conversations/tickets in later Phase 19 chunks)
 * that surfaces `created_at`/`updated_at` fields.
 */
const FORMATTER = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

export function Timestamp({ value, className }: { value: string; className?: string }) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    // Untrusted/unexpected backend data — never crash the page over a
    // malformed timestamp; fall back to the raw value rather than hiding it.
    return <span className={className}>{value}</span>;
  }
  return (
    <time dateTime={value} className={className}>
      {FORMATTER.format(date)}
    </time>
  );
}
