import { EnumBadge } from "@/components/support/enum-badge";
import type { ConversationChannelValue, ConversationStatusValue } from "@/features/conversations/types";

const STATUS_LABELS: Record<ConversationStatusValue, string> = {
  open: "Open",
  pending: "Pending",
  closed: "Closed",
};

const STATUS_VARIANTS: Record<ConversationStatusValue, "success" | "warning" | "neutral"> = {
  open: "success",
  pending: "warning",
  closed: "neutral",
};

export function ConversationStatusBadge({ status }: { status: ConversationStatusValue }) {
  return <EnumBadge value={status} labels={STATUS_LABELS} variants={STATUS_VARIANTS} />;
}

const CHANNEL_LABELS: Record<ConversationChannelValue, string> = {
  web: "Web",
  chat: "Chat",
  email: "Email",
  sms: "SMS",
  api: "API",
};

export function ConversationChannelBadge({ channel }: { channel: ConversationChannelValue }) {
  return (
    <EnumBadge value={channel} labels={CHANNEL_LABELS} variants={{}} fallbackVariant="neutral" />
  );
}
