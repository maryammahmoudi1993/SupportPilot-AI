/**
 * Typed, workspace-scoped query key factory for the tickets domain — same
 * policy as customers/conversations (see features/customers/query-keys.ts):
 * every key embeds the workspace ID as its second segment, so a workspace
 * switch produces a disjoint cache entry, never a stale one Workspace B
 * could render.
 */
import type { TicketListParams } from "@/features/tickets/types";

export const ticketKeys = {
  all: (workspaceId: string) => ["workspaces", workspaceId, "tickets"] as const,
  lists: (workspaceId: string) => [...ticketKeys.all(workspaceId), "list"] as const,
  list: (workspaceId: string, params: TicketListParams) =>
    [...ticketKeys.lists(workspaceId), params] as const,
  details: (workspaceId: string) => [...ticketKeys.all(workspaceId), "detail"] as const,
  detail: (workspaceId: string, ticketId: string) =>
    [...ticketKeys.details(workspaceId), ticketId] as const,
};
