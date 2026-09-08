import Link from "next/link";

/**
 * Links to a conversation's customer using only the customer ID — the
 * conversation list/detail API does not embed a customer summary (name,
 * email, ...), only `customer_id` (see conversations/serializers.py
 * `ConversationSerializer`). Fetching each row's customer name
 * individually would be a client-side N+1 (see frontend/README.md,
 * "Customer identity in the inbox" for the full architectural note), so
 * this deliberately shows an honest, real reference — not a fabricated
 * name — rather than either an N+1 fetch or a fake-looking blank.
 */
export function CustomerRefLink({ customerId, className }: { customerId: string; className?: string }) {
  return (
    <Link
      href={`/app/customers/${customerId}`}
      className={className ?? "text-primary-700 hover:underline focus-visible:underline"}
    >
      Customer #{customerId.slice(0, 8)}
    </Link>
  );
}
