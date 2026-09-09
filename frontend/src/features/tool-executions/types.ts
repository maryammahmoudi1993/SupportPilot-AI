/**
 * Tool Execution domain types (Phase 20 Chunk 2: Tool Executions + Execution
 * Trace).
 *
 * Re-exported from the generated OpenAPI schema — `ToolExecution` is fully
 * server-derived (`read_only_fields = fields`, see tools/serializers.py), so
 * no write-shape narrowing is needed beyond the list-filter gap documented
 * in api.ts.
 *
 * Schema gap (Category B — generated type present but misleadingly named):
 * `ToolDefinition.status` is generated as `WebhookEndpointStatusEnum`
 * (`"active" | "disabled"`) rather than a tool-specific enum name —
 * drf-spectacular's component-naming collision, reusing an unrelated
 * schema's name because both are simple two-value status choices with the
 * same literal values (tools/models.py `ToolDefinitionStatus` — "active" /
 * "disabled" — matches exactly). The values are correct; only the generated
 * TypeScript name is confusing. Re-typed below as `ToolDefinitionStatusValue`
 * so calling code never has to reference `WebhookEndpointStatusEnum`.
 */
import type { components } from "@/types/api";

export type ToolExecution = components["schemas"]["ToolExecution"];
export type PaginatedToolExecutionList = components["schemas"]["PaginatedToolExecutionList"];
export type ToolExecutionStatusValue = components["schemas"]["ToolExecutionStatusEnum"];

export type ToolDefinition = Omit<components["schemas"]["ToolDefinition"], "status"> & {
  status: ToolDefinitionStatusValue;
};
export type PaginatedToolDefinitionList = Omit<
  components["schemas"]["PaginatedToolDefinitionList"],
  "results"
> & { results: ToolDefinition[] };
export type ToolDefinitionStatusValue = "active" | "disabled";
export type RiskLevelValue = components["schemas"]["RiskLevelEnum"];
export type SideEffectTypeValue = components["schemas"]["SideEffectTypeEnum"];

/**
 * The backend's real terminal-status set for a `ToolExecution`
 * (tools/models.py `TOOL_EXECUTION_TERMINAL_STATUSES`) — mirrored here
 * rather than imported (frontend/backend are separate deployables).
 */
export const TOOL_EXECUTION_TERMINAL_STATUSES: ReadonlySet<ToolExecutionStatusValue> = new Set([
  "succeeded",
  "failed",
  "timed_out",
  "cancelled",
  "blocked_by_policy",
  "approval_terminated",
]);

export function isTerminalToolExecutionStatus(status: ToolExecutionStatusValue): boolean {
  return TOOL_EXECUTION_TERMINAL_STATUSES.has(status);
}

/**
 * A read-only approval-context label derived entirely from `ToolExecution`'s
 * own real fields — never a separate Approval-domain fetch (Chunk 3 owns
 * that UI; see the build prompt Part F). `approval_terminated`'s specific
 * reason is recorded in `error_code` as one of `approval_rejected` /
 * `approval_expired` / `approval_cancelled` (tools/models.py
 * `ToolExecutionStatus.APPROVAL_TERMINATED`'s docstring) — an unrecognized
 * future error_code falls back to a generic, still-accurate label rather
 * than guessing.
 */
export type ApprovalContext =
  | { kind: "none" }
  | { kind: "waiting" }
  | { kind: "blocked_by_policy" }
  | { kind: "rejected" }
  | { kind: "expired" }
  | { kind: "cancelled" }
  | { kind: "terminated_other" };

export function deriveApprovalContext(execution: ToolExecution): ApprovalContext {
  if (execution.status === "waiting_for_approval") {
    return { kind: "waiting" };
  }
  if (execution.status === "blocked_by_policy") {
    return { kind: "blocked_by_policy" };
  }
  if (execution.status === "approval_terminated") {
    switch (execution.error_code) {
      case "approval_rejected":
        return { kind: "rejected" };
      case "approval_expired":
        return { kind: "expired" };
      case "approval_cancelled":
        return { kind: "cancelled" };
      default:
        return { kind: "terminated_other" };
    }
  }
  return { kind: "none" };
}
