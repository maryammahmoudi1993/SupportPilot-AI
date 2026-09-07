import { WorkspaceSwitcher } from "@/features/workspace/workspace-switcher";
import { MobileNav } from "@/components/shell/mobile-nav";
import { UserMenu } from "@/components/shell/user-menu";

/** Page-title/breadcrumb slot: a plain heading for now — no route yet needs a real breadcrumb trail. */
export function Header({ title }: { title?: string }) {
  return (
    <header
      className="border-border-subtle bg-surface-0 flex h-(--shell-header-height) shrink-0 items-center justify-between gap-3 border-b px-4"
      aria-label="Header"
    >
      <div className="flex min-w-0 items-center gap-3">
        <MobileNav />
        {title && <h1 className="text-text-primary truncate text-sm font-semibold">{title}</h1>}
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <WorkspaceSwitcher />
        <UserMenu />
      </div>
    </header>
  );
}
