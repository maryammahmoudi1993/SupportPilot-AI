/**
 * Typed navigation configuration for the app shell's sidebar/mobile nav.
 *
 * Phase 18 Chunk 3 implemented the application shell only, with a single
 * "Overview" entry. Phase 19 Chunk 1 added "Customers" once `/app/customers`
 * became a real route with real data. Phase 19 Chunk 2 added "Inbox" once
 * `/app/inbox` was real too. Phase 19 Chunk 3 adds "Tickets" now that
 * `/app/tickets` is real. Phase 20 Chunk 1 adds "Agent Runs" now that
 * `/app/agent-runs` is real — see frontend/README.md, "Navigation". A stable
 * `id`/`path` per entry lets feature code (e.g. workspace-scoped query-key
 * conventions) reference a destination without coupling to its label or
 * position. Do not add a destination whose route does not yet exist — an
 * unclickable/fake nav entry is worse than a short sidebar. Phase 20 Chunk 3
 * adds "Approvals" and "Handoffs" now that `/app/approvals` and
 * `/app/handoffs` are real. Phase 21 Chunk 1 adds "Knowledge" now that
 * `/app/knowledge` is real. Phase 22 Chunk 1 adds "Integrations" now that
 * `/app/integrations` is real — one coherent entry per master prompt Part G
 * §27, not separate Webhooks/Notifications/Deliveries entries (those remain
 * deferred to a later Phase 22 chunk, and will live under this same route
 * family as tabs/subroutes rather than new top-level nav items).
 */
export interface NavItem {
  id: string;
  label: string;
  /** Root-relative path, resolved against the active workspace by the caller if needed. */
  path: string;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { id: "overview", label: "Overview", path: "/app" },
  { id: "inbox", label: "Inbox", path: "/app/inbox" },
  { id: "customers", label: "Customers", path: "/app/customers" },
  { id: "tickets", label: "Tickets", path: "/app/tickets" },
  { id: "agent-runs", label: "Agent Runs", path: "/app/agent-runs" },
  { id: "approvals", label: "Approvals", path: "/app/approvals" },
  { id: "handoffs", label: "Handoffs", path: "/app/handoffs" },
  { id: "knowledge", label: "Knowledge", path: "/app/knowledge" },
  { id: "integrations", label: "Integrations", path: "/app/integrations" },
];
