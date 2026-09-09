import { EnumBadge } from "@/components/support/enum-badge";
import type {
  ApprovalContext,
  RiskLevelValue,
  SideEffectTypeValue,
  ToolExecutionStatusValue,
} from "@/features/tool-executions/types";

const STATUS_LABELS: Partial<Record<ToolExecutionStatusValue, string>> = {
  pending: "Pending",
  running: "Running",
  succeeded: "Succeeded",
  failed: "Failed",
  timed_out: "Timed out",
  cancelled: "Cancelled",
  waiting_for_approval: "Waiting for approval",
  blocked_by_policy: "Blocked by policy",
  approval_terminated: "Approval terminated",
};

const STATUS_VARIANTS: Partial<
  Record<ToolExecutionStatusValue, "success" | "warning" | "danger" | "primary" | "neutral">
> = {
  pending: "neutral",
  running: "primary",
  succeeded: "success",
  failed: "danger",
  timed_out: "danger",
  cancelled: "neutral",
  waiting_for_approval: "warning",
  blocked_by_policy: "danger",
  approval_terminated: "warning",
};

/** Unknown future status: falls back to the raw value with a neutral variant. */
export function ToolExecutionStatusBadge({ status }: { status: ToolExecutionStatusValue }) {
  return <EnumBadge value={status} labels={STATUS_LABELS} variants={STATUS_VARIANTS} />;
}

const RISK_LABELS: Partial<Record<RiskLevelValue, string>> = {
  read_only: "Read only",
  low: "Low risk",
  medium: "Medium risk",
  high: "High risk",
  critical: "Critical risk",
};

const RISK_VARIANTS: Partial<Record<RiskLevelValue, "neutral" | "warning" | "danger">> = {
  read_only: "neutral",
  low: "neutral",
  medium: "warning",
  high: "danger",
  critical: "danger",
};

/** From the real tool catalog (`ToolDefinition.risk_level`) — never derived from the tool's name/key. */
export function RiskLevelBadge({ level }: { level: RiskLevelValue }) {
  return <EnumBadge value={level} labels={RISK_LABELS} variants={RISK_VARIANTS} />;
}

const SIDE_EFFECT_LABELS: Partial<Record<SideEffectTypeValue, string>> = {
  none: "No side effect",
  read: "Read",
  internal_write: "Internal write",
  external_write: "External write",
  financial: "Financial",
  destructive: "Destructive",
};

const SIDE_EFFECT_VARIANTS: Partial<Record<SideEffectTypeValue, "neutral" | "warning" | "danger">> =
  {
    none: "neutral",
    read: "neutral",
    internal_write: "neutral",
    external_write: "warning",
    financial: "danger",
    destructive: "danger",
  };

export function SideEffectBadge({ type }: { type: SideEffectTypeValue }) {
  return <EnumBadge value={type} labels={SIDE_EFFECT_LABELS} variants={SIDE_EFFECT_VARIANTS} />;
}

/**
 * Read-only approval context (master prompt Part F §20-21) — text only, no
 * Approve/Reject action, no link to a not-yet-existing Approval route.
 * `{ kind: "none" }` renders nothing: most tool executions were never
 * gated, and a blank line is more honest than an "N/A" for every row.
 * `"waiting"`/`"blocked_by_policy"` also render nothing here — the
 * execution's own status badge (`ToolExecutionStatusBadge`) already says
 * exactly that ("Waiting for approval"/"Blocked by policy"); this note adds
 * value only for `approval_terminated`, where the badge's generic label
 * ("Approval terminated") doesn't carry the specific real reason.
 */
export function ApprovalContextNote({ context }: { context: ApprovalContext }) {
  switch (context.kind) {
    case "none":
    case "waiting":
    case "blocked_by_policy":
      return null;
    case "rejected":
      return <span className="text-danger-700 text-xs font-medium">Approval rejected</span>;
    case "expired":
      return <span className="text-danger-700 text-xs font-medium">Approval expired</span>;
    case "cancelled":
      return <span className="text-text-secondary text-xs font-medium">Approval cancelled</span>;
    case "terminated_other":
      return <span className="text-text-secondary text-xs font-medium">Approval terminated</span>;
  }
}
