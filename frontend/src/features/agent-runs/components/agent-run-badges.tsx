import { EnumBadge } from "@/components/support/enum-badge";
import type { AgentRunStatusValue, AgentStepStatusValue } from "@/features/agent-runs/types";

const STATUS_LABELS: Partial<Record<AgentRunStatusValue, string>> = {
  pending: "Pending",
  running: "Running",
  succeeded: "Succeeded",
  failed: "Failed",
  cancelled: "Cancelled",
  budget_exceeded: "Budget exceeded",
  waiting_for_approval: "Waiting for approval",
  handed_off: "Handed off",
};

const STATUS_VARIANTS: Partial<
  Record<AgentRunStatusValue, "success" | "warning" | "danger" | "primary" | "neutral">
> = {
  pending: "neutral",
  running: "primary",
  succeeded: "success",
  failed: "danger",
  cancelled: "neutral",
  budget_exceeded: "danger",
  waiting_for_approval: "warning",
  handed_off: "warning",
};

/**
 * Unknown future status value: falls back to the raw value with a neutral
 * variant (EnumBadge's default) rather than crashing or hiding the row —
 * see master prompt Part F-24, "unknown future enum: safe fallback".
 */
export function AgentRunStatusBadge({ status }: { status: AgentRunStatusValue }) {
  return <EnumBadge value={status} labels={STATUS_LABELS} variants={STATUS_VARIANTS} />;
}

const STEP_STATUS_LABELS: Partial<Record<AgentStepStatusValue, string>> = {
  started: "Started",
  succeeded: "Succeeded",
  failed: "Failed",
};

const STEP_STATUS_VARIANTS: Partial<
  Record<AgentStepStatusValue, "success" | "danger" | "neutral">
> = {
  started: "neutral",
  succeeded: "success",
  failed: "danger",
};

export function AgentStepStatusBadge({ status }: { status: AgentStepStatusValue }) {
  return <EnumBadge value={status} labels={STEP_STATUS_LABELS} variants={STEP_STATUS_VARIANTS} />;
}
