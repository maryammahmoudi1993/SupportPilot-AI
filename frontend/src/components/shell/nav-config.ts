/**
 * Typed navigation configuration for the app shell's sidebar/mobile nav.
 *
 * Phase 18 Chunk 3 implemented the application shell only, with a single
 * "Overview" entry. Phase 19 Chunk 1 adds "Customers" now that
 * `/app/customers` is a real route with real data — see
 * frontend/README.md, "Navigation". Conversations/Inbox and Tickets are
 * added in later Phase 19 chunks, once their routes actually exist. A
 * stable `id`/`path` per entry lets feature code (e.g. workspace-scoped
 * query-key conventions) reference a destination without coupling to its
 * label or position. Do not add a destination whose route does not yet
 * exist — an unclickable/fake nav entry is worse than a short sidebar.
 */
export interface NavItem {
  id: string;
  label: string;
  /** Root-relative path, resolved against the active workspace by the caller if needed. */
  path: string;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { id: "overview", label: "Overview", path: "/app" },
  { id: "customers", label: "Customers", path: "/app/customers" },
];
