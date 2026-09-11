import { Badge } from "@/components/ui/badge";
import { EnumBadge } from "@/components/support/enum-badge";
import type {
  EvaluationCaseStatusValue,
  EvaluationDatasetStatusValue,
  EvaluationResultStatusValue,
  EvaluationRunStatusValue,
} from "@/features/evaluations/types";

const RUN_STATUS_LABELS: Partial<Record<EvaluationRunStatusValue, string>> = {
  pending: "Pending",
  running: "Running",
  succeeded: "Succeeded",
  partial: "Partial",
  failed: "Failed",
  cancelled: "Cancelled",
};

const RUN_STATUS_VARIANTS: Partial<
  Record<EvaluationRunStatusValue, "success" | "warning" | "danger" | "primary" | "neutral">
> = {
  pending: "neutral",
  running: "primary",
  succeeded: "success",
  partial: "warning",
  failed: "danger",
  cancelled: "neutral",
};

/**
 * Unknown future status value: falls back to the raw value with a neutral
 * variant (EnumBadge's default) rather than crashing or hiding the row — see
 * master prompt Part F-21, "unknown future status: safe text fallback".
 */
export function EvaluationRunStatusBadge({ status }: { status: EvaluationRunStatusValue }) {
  return <EnumBadge value={status} labels={RUN_STATUS_LABELS} variants={RUN_STATUS_VARIANTS} />;
}

const RESULT_STATUS_LABELS: Partial<Record<EvaluationResultStatusValue, string>> = {
  pending: "Pending",
  running: "Running",
  succeeded: "Succeeded",
  failed: "Failed",
  cancelled: "Cancelled",
};

const RESULT_STATUS_VARIANTS: Partial<
  Record<EvaluationResultStatusValue, "success" | "danger" | "neutral" | "primary">
> = {
  pending: "neutral",
  running: "primary",
  succeeded: "success",
  failed: "danger",
  cancelled: "neutral",
};

export function EvaluationResultStatusBadge({ status }: { status: EvaluationResultStatusValue }) {
  return (
    <EnumBadge value={status} labels={RESULT_STATUS_LABELS} variants={RESULT_STATUS_VARIANTS} />
  );
}

/**
 * `passed` is the backend's own authoritative outcome
 * (evaluations/scoring.py `score_case`'s `not violations` — never a
 * client-derived threshold, master prompt Part B §13). `null` means "not yet
 * scored" (a pending/running/cancelled result, or one whose scoring itself
 * failed) — rendered as its own distinct, non-color-only state rather than
 * folded into either Passed or Failed.
 */
export function EvaluationPassedBadge({ passed }: { passed: boolean | null }) {
  if (passed === null) {
    return <Badge variant="neutral">Not scored</Badge>;
  }
  return passed ? (
    <Badge variant="success">Passed</Badge>
  ) : (
    <Badge variant="danger">Failed</Badge>
  );
}

const DATASET_STATUS_LABELS: Partial<Record<EvaluationDatasetStatusValue, string>> = {
  draft: "Draft",
  active: "Active",
  archived: "Archived",
};

const DATASET_STATUS_VARIANTS: Partial<
  Record<EvaluationDatasetStatusValue, "success" | "warning" | "neutral" | "primary" | "danger">
> = {
  draft: "neutral",
  active: "success",
  archived: "warning",
};

export function EvaluationDatasetStatusBadge({ status }: { status: EvaluationDatasetStatusValue }) {
  return (
    <EnumBadge value={status} labels={DATASET_STATUS_LABELS} variants={DATASET_STATUS_VARIANTS} />
  );
}

const CASE_STATUS_LABELS: Partial<Record<EvaluationCaseStatusValue, string>> = {
  active: "Active",
  disabled: "Disabled",
};

const CASE_STATUS_VARIANTS: Partial<
  Record<EvaluationCaseStatusValue, "success" | "neutral" | "primary" | "warning" | "danger">
> = {
  active: "success",
  disabled: "neutral",
};

export function EvaluationCaseStatusBadge({ status }: { status: EvaluationCaseStatusValue }) {
  return <EnumBadge value={status} labels={CASE_STATUS_LABELS} variants={CASE_STATUS_VARIANTS} />;
}
