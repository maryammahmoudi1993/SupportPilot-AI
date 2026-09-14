"use client";

import Link from "next/link";

/**
 * Real navigation links between the two Settings sub-routes (never ARIA
 * tabs — same pattern as `integrations-list-page.tsx`'s `TabLink`, per the
 * Phase 21 Chunk 4 accessibility fix this codebase already made once:
 * a `<nav>` landmark with `aria-current="page"`, not a `role="tablist"`
 * around plain links, since there is no roving tabindex or `role="tabpanel"`
 * pairing here). One coherent "Settings" top-level nav entry (master prompt
 * Part D §16-17) hosts these as its own real, bookmarkable routes.
 */
export function SettingsNav({ active }: { active: "members" | "workspace" }) {
  return (
    <nav aria-label="Settings views" className="flex gap-2">
      <Link
        href="/app/settings/members"
        aria-current={active === "members" ? "page" : undefined}
        className={
          active === "members"
            ? "bg-primary-500 text-text-inverse rounded-md px-3 py-1.5 text-sm font-medium"
            : "text-text-secondary hover:bg-surface-2 hover:text-text-primary rounded-md px-3 py-1.5 text-sm font-medium transition-colors"
        }
      >
        Members
      </Link>
      <Link
        href="/app/settings/workspace"
        aria-current={active === "workspace" ? "page" : undefined}
        className={
          active === "workspace"
            ? "bg-primary-500 text-text-inverse rounded-md px-3 py-1.5 text-sm font-medium"
            : "text-text-secondary hover:bg-surface-2 hover:text-text-primary rounded-md px-3 py-1.5 text-sm font-medium transition-colors"
        }
      >
        Workspace
      </Link>
    </nav>
  );
}
