import { EnumBadge } from "@/components/support/enum-badge";
import type { HumanHandoffReasonValue, HumanHandoffStatusValue } from "@/features/handoffs/types";

const STATUS_LABELS: Partial<Record<HumanHandoffStatusValue, string>> = {
  pending: "Pending",
  assigned: "Assigned",
  resolved: "Resolved",
  cancelled: "Cancelled",
};

const STATUS_VARIANTS: Partial<
  Record<HumanHandoffStatusValue, "success" | "warning" | "danger" | "primary" | "neutral">
> = {
  pending: "warning",
  assigned: "primary",
  resolved: "success",
  cancelled: "neutral",
};

/** Unknown future status value: safe neutral fallback (master prompt Part A §4 pattern, applied here too). */
export function HandoffStatusBadge({ status }: { status: HumanHandoffStatusValue }) {
  return <EnumBadge value={status} labels={STATUS_LABELS} variants={STATUS_VARIANTS} />;
}

const REASON_LABELS: Partial<Record<HumanHandoffReasonValue, string>> = {
  customer_requested: "Customer requested a human",
  unsupported_action: "Unsupported action",
  runtime_failure: "Repeated bounded runtime failure",
  low_confidence: "Low-confidence retrieval/response",
  policy_escalation: "Business workflow requires an operator",
};

export function handoffReasonLabel(reason: HumanHandoffReasonValue): string {
  return REASON_LABELS[reason] ?? reason;
}
