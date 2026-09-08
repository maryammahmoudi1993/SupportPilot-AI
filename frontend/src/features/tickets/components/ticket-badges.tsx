import { EnumBadge } from "@/components/support/enum-badge";
import type { TicketPriorityValue, TicketStatusValue } from "@/features/tickets/types";

const STATUS_LABELS: Record<TicketStatusValue, string> = {
  open: "Open",
  in_progress: "In Progress",
  pending: "Pending",
  resolved: "Resolved",
  closed: "Closed",
};

const STATUS_VARIANTS: Record<TicketStatusValue, "success" | "warning" | "neutral"> = {
  open: "success",
  in_progress: "warning",
  pending: "warning",
  resolved: "neutral",
  closed: "neutral",
};

export function TicketStatusBadge({ status }: { status: TicketStatusValue }) {
  return <EnumBadge value={status} labels={STATUS_LABELS} variants={STATUS_VARIANTS} />;
}

const PRIORITY_LABELS: Record<TicketPriorityValue, string> = {
  low: "Low",
  normal: "Normal",
  high: "High",
  urgent: "Urgent",
};

const PRIORITY_VARIANTS: Record<TicketPriorityValue, "danger" | "warning" | "neutral"> = {
  urgent: "danger",
  high: "warning",
  normal: "neutral",
  low: "neutral",
};

export function TicketPriorityBadge({ priority }: { priority: TicketPriorityValue }) {
  return <EnumBadge value={priority} labels={PRIORITY_LABELS} variants={PRIORITY_VARIANTS} />;
}
