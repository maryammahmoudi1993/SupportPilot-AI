import { EnumBadge } from "@/components/support/enum-badge";
import type { ApprovalStatusValue } from "@/features/approvals/types";

const STATUS_LABELS: Partial<Record<ApprovalStatusValue, string>> = {
  pending: "Pending",
  approved: "Approved",
  rejected: "Rejected",
  expired: "Expired",
  cancelled: "Cancelled",
};

const STATUS_VARIANTS: Partial<
  Record<ApprovalStatusValue, "success" | "warning" | "danger" | "primary" | "neutral">
> = {
  pending: "warning",
  approved: "success",
  rejected: "danger",
  expired: "neutral",
  cancelled: "neutral",
};

/**
 * Unknown future status value: falls back to the raw value with a neutral
 * variant rather than crashing or hiding the row (master prompt Part A §4,
 * "unknown future values: safe fallback").
 */
export function ApprovalStatusBadge({ status }: { status: ApprovalStatusValue }) {
  return <EnumBadge value={status} labels={STATUS_LABELS} variants={STATUS_VARIANTS} />;
}
