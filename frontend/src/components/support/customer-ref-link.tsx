import Link from "next/link";

/**
 * Links to a customer using only the customer ID. Shared across every
 * domain whose API only embeds `customer_id` (conversations, tickets — see
 * conversations/serializers.py `ConversationSerializer` and
 * tickets/serializers.py `TicketSerializer`), never a nested customer
 * summary (name, email, ...). Fetching each row's customer name
 * individually would be a client-side N+1 (see frontend/README.md,
 * "Customer identity in the inbox" for the full architectural note), so
 * this deliberately shows an honest, real reference — not a fabricated
 * name — rather than either an N+1 fetch or a fake-looking blank.
 *
 * A single shared component, not a per-domain copy: two domains rendering
 * the same "Customer #12345678" reference must never drift in behavior.
 */
export function CustomerRefLink({
  customerId,
  className,
}: {
  customerId: string;
  className?: string;
}) {
  return (
    <Link
      href={`/app/customers/${customerId}`}
      className={className ?? "text-primary-700 hover:underline focus-visible:underline"}
    >
      Customer #{customerId.slice(0, 8)}
    </Link>
  );
}
