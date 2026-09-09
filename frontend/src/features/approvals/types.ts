/**
 * Approval domain types (Phase 20 Chunk 3: Approvals + Human Handoff
 * Operational Workflows).
 *
 * `ApprovalRequest`/`ApprovalDecision` are otherwise fully server-derived
 * (`read_only_fields = fields`, see backend/approvals/serializers.py), but
 * two real gaps need narrowing here:
 *
 * Schema gap (Category A — a real value the generated type gets wrong, not
 * just an unhelpfully-named one): the generated `ApprovalRequest.decision`
 * is typed as `ApprovalDecision` (non-nullable), but a *pending* approval
 * has no `ApprovalDecision` row yet — verified directly against the real
 * serializer (`approvals/serializers.py` `ApprovalRequestSerializer`,
 * `decision = ApprovalDecisionSerializer(read_only=True)` with no
 * `allow_null`/default handling on the model's reverse one-to-one
 * accessor): a pending request serializes `"decision": null`. Re-typed
 * below as `ApprovalDecision | null`.
 *
 * Schema gap (Category A — an untyped real field): `safe_context` is
 * generated as `unknown`. The real shape (`approvals/services.py`
 * `create_or_reuse_approval_request`) is `{ tool_key, tool_display_name,
 * risk_level, side_effect_type, policy_reason, arguments }` — all optional
 * here defensively, since nothing server-side guarantees every key is
 * always present (e.g. a future approval source), and this is rendered via
 * `StructuredPayload`, not destructured for logic, except `tool_key`/
 * `tool_display_name` (both plain, human-facing labels).
 */
import type { components } from "@/types/api";

export type ApprovalStatusValue = components["schemas"]["ApprovalStatusEnum"];
export type ApprovalDecisionValueEnum = components["schemas"]["ApprovalDecisionValueEnum"];
export type ApprovalDecision = components["schemas"]["ApprovalDecision"];

export interface ApprovalSafeContext {
  tool_key?: string;
  tool_display_name?: string;
  risk_level?: string;
  side_effect_type?: string;
  policy_reason?: string;
  arguments?: unknown;
}

export type ApprovalRequest = Omit<
  components["schemas"]["ApprovalRequest"],
  "decision" | "safe_context"
> & {
  decision: ApprovalDecision | null;
  safe_context: unknown;
};

export type PaginatedApprovalRequestList = Omit<
  components["schemas"]["PaginatedApprovalRequestList"],
  "results"
> & { results: ApprovalRequest[] };

/**
 * The backend's real terminal-status set (approvals/models.py
 * `APPROVAL_TERMINAL_STATUSES`) — mirrored here rather than imported
 * (frontend/backend are separate deployables). Only `pending` is
 * actionable (Approve/Reject shown); every other status — including any
 * future value this frontend doesn't yet recognize — is treated as
 * non-actionable, never assumed decidable.
 */
export const APPROVAL_TERMINAL_STATUSES: ReadonlySet<ApprovalStatusValue> = new Set([
  "approved",
  "rejected",
  "expired",
  "cancelled",
]);

export function isTerminalApprovalStatus(status: ApprovalStatusValue): boolean {
  return APPROVAL_TERMINAL_STATUSES.has(status);
}

export function isActionableApprovalStatus(status: ApprovalStatusValue): boolean {
  return status === "pending";
}

/** `"all"` omits the corresponding filter from the request entirely. */
export type ApprovalStatusFilter = "all" | ApprovalStatusValue;

export interface ApprovalListParams {
  page: number;
  status: ApprovalStatusFilter;
}

export const DEFAULT_APPROVAL_LIST_PARAMS: ApprovalListParams = {
  page: 1,
  status: "pending",
};

/**
 * Server-derived role rank (approvals/services.py `_APPROVAL_ROLE_RANK`,
 * `role_satisfies_requirement`) — mirrored here only to decide whether to
 * *show* Approve/Reject controls at all (a UX convenience, never the
 * authorization boundary: the backend re-checks this on every decide call
 * regardless of what the UI renders). An unrecognized `required_role`
 * value safely renders no controls rather than guessing.
 */
const APPROVAL_ROLE_RANK: Readonly<Record<string, number>> = {
  support_manager: 1,
  admin: 2,
  owner: 3,
};

export function roleSatisfiesRequirement(actorRole: string, requiredRole: string): boolean {
  const actorRank = APPROVAL_ROLE_RANK[actorRole] ?? 0;
  const requiredRank = APPROVAL_ROLE_RANK[requiredRole] ?? 99;
  return actorRank >= requiredRank;
}
