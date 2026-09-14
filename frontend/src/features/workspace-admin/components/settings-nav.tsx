"use client";

import Link from "next/link";

/**
 * Real navigation links between the Settings sub-routes (never ARIA tabs —
 * same pattern as `integrations-list-page.tsx`'s `TabLink`, per the Phase 21
 * Chunk 4 accessibility fix this codebase already made once: a `<nav>`
 * landmark with `aria-current="page"`, not a `role="tablist"` around plain
 * links, since there is no roving tabindex or `role="tabpanel"` pairing
 * here). One coherent "Settings" top-level nav entry (master prompt Part D
 * §16-17) hosts these as its own real, bookmarkable routes. Phase 24 Chunk 3
 * adds "Account" — a real, read-only `/auth/me/`-backed page; see
 * `account-settings-page.tsx`'s module doc comment for why it has no edit
 * capability.
 */
type SettingsTab = "members" | "workspace" | "account";

const TABS: { id: SettingsTab; href: string; label: string }[] = [
  { id: "members", href: "/app/settings/members", label: "Members" },
  { id: "workspace", href: "/app/settings/workspace", label: "Workspace" },
  { id: "account", href: "/app/settings/account", label: "Account" },
];

export function SettingsNav({ active }: { active: SettingsTab }) {
  return (
    <nav aria-label="Settings views" className="flex gap-2">
      {TABS.map((tab) => (
        <Link
          key={tab.id}
          href={tab.href}
          aria-current={active === tab.id ? "page" : undefined}
          className={
            active === tab.id
              ? "bg-primary-500 text-text-inverse rounded-md px-3 py-1.5 text-sm font-medium"
              : "text-text-secondary hover:bg-surface-2 hover:text-text-primary rounded-md px-3 py-1.5 text-sm font-medium transition-colors"
          }
        >
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}
