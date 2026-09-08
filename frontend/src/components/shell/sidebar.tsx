import { NavLinks } from "@/components/shell/nav-links";

/** Desktop-only (hidden below `md`; `MobileNav` covers small viewports). */
export function Sidebar() {
  return (
    <aside
      className="border-border-subtle bg-surface-0 hidden w-(--shell-sidebar-width) shrink-0 flex-col border-r md:flex"
      aria-label="Sidebar"
    >
      <div className="flex h-(--shell-header-height) shrink-0 items-center px-4">
        <span className="text-text-primary text-sm font-semibold">SupportPilot AI</span>
      </div>
      <div className="flex-1 overflow-y-auto px-3 pb-4">
        <NavLinks />
      </div>
    </aside>
  );
}
