/**
 * Human Handoff domain types (Phase 20 Chunk 3). `HumanHandoff` is fully
 * server-derived (`read_only_fields = fields`, see backend/tickets/
 * serializers.py `HumanHandoffSerializer`), so no write-shape narrowing is
 * needed — this chunk implements no handoff mutation (master prompt Part G
 * §31: "Read-only is acceptable"; see frontend/README.md for why `assign`/
 * `resolve`, though real endpoints, are out of this chunk's scope).
 */
import type { components } from "@/types/api";

export type HumanHandoffStatusValue = components["schemas"]["HumanHandoffStatusEnum"];
export type HumanHandoffReasonValue = components["schemas"]["ReasonCodeEnum"];
export type HumanHandoff = components["schemas"]["HumanHandoff"];
export type PaginatedHumanHandoffList = components["schemas"]["PaginatedHumanHandoffList"];

/**
 * The backend's real active-status set (tickets/models.py
 * `HUMAN_HANDOFF_ACTIVE_STATUSES`) — mirrored here rather than imported
 * (frontend/backend are separate deployables).
 */
export const HUMAN_HANDOFF_ACTIVE_STATUSES: ReadonlySet<HumanHandoffStatusValue> = new Set([
  "pending",
  "assigned",
]);

export function isActiveHandoffStatus(status: HumanHandoffStatusValue): boolean {
  return HUMAN_HANDOFF_ACTIVE_STATUSES.has(status);
}

/** `"all"` omits the corresponding filter from the request entirely. */
export type HandoffStatusFilter = "all" | HumanHandoffStatusValue;

export interface HandoffListParams {
  page: number;
  status: HandoffStatusFilter;
}

export const DEFAULT_HANDOFF_LIST_PARAMS: HandoffListParams = {
  page: 1,
  status: "all",
};
