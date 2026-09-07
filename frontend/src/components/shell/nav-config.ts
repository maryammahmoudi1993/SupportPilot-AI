/**
 * Typed navigation configuration for the app shell's sidebar/mobile nav.
 *
 * Phase 18 Chunk 3 implements the application shell only — no business-
 * domain pages (conversations, customers, tickets, ...) exist yet, so this
 * list intentionally has exactly one entry. Later phases add destinations
 * here as their routes actually ship; a stable `id`/`path` per entry lets
 * feature code (e.g. workspace-scoped query-key conventions) reference a
 * destination without coupling to its label or position. Do not add a
 * destination whose route does not yet exist — an unclickable/fake nav
 * entry is worse than a short sidebar (see frontend/README.md, "Navigation").
 */
export interface NavItem {
  id: string;
  label: string;
  /** Root-relative path, resolved against the active workspace by the caller if needed. */
  path: string;
}

export const NAV_ITEMS: readonly NavItem[] = [{ id: "overview", label: "Overview", path: "/app" }];
