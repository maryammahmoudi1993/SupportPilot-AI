import { EnumBadge } from "@/components/support/enum-badge";
import { Timestamp } from "@/components/support/timestamp";
import type { Message } from "@/features/conversations/types";
import { cn } from "@/lib/utils";

const SENDER_TYPE_LABELS: Record<Message["sender_type"], string> = {
  customer: "Customer",
  human_agent: "Support agent",
  ai_agent: "AI agent",
  system: "System",
};

function senderLabel(message: Message): string {
  if (message.sender_type === "human_agent" && message.sender) {
    return message.sender.email;
  }
  return SENDER_TYPE_LABELS[message.sender_type] ?? "Unknown sender";
}

/**
 * A plain `<ol>`/`<li>` list, not `role="log"` — this timeline is a static
 * page load, not a live-updating region (see frontend/README.md,
 * "Accessible timeline"). Message order is rendered exactly as the backend
 * returned it (oldest first, `(created_at, sequence)` — see api.ts's
 * `fetchMessageList` doc comment) and never re-sorted client-side.
 */
export function MessageTimeline({ messages }: { messages: Message[] }) {
  return (
    <ol className="flex flex-col gap-3">
      {messages.map((message) => {
        const isInternal = message.direction === "internal";
        return (
          <li
            key={message.id}
            className={cn(
              "rounded-md border p-3 border-border-subtle",
              isInternal ? "bg-warning-50" : "bg-surface-0",
            )}
          >
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <span className="text-text-primary text-sm font-medium">{senderLabel(message)}</span>
              <div className="flex items-center gap-2">
                {isInternal && (
                  <EnumBadge
                    value="internal"
                    labels={{ internal: "Internal note" }}
                    variants={{ internal: "warning" }}
                  />
                )}
                <Timestamp value={message.created_at} className="text-text-muted text-xs" />
              </div>
            </div>
            <p className="text-text-primary mt-1.5 text-sm break-words whitespace-pre-wrap">
              {message.body}
            </p>
          </li>
        );
      })}
    </ol>
  );
}
