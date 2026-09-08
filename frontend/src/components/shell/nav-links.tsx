"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { NAV_ITEMS } from "@/components/shell/nav-config";
import { cn } from "@/lib/utils";

/**
 * Shared between the desktop sidebar and the mobile drawer. `usePathname`
 * makes this a Client Component (layouts don't re-render on navigation, so
 * only a client hook sees the current route) — see frontend/README.md,
 * "Client/server boundaries".
 */
export function NavLinks({
  onNavigate,
  className,
}: {
  onNavigate?: () => void;
  className?: string;
}) {
  const pathname = usePathname();

  return (
    <nav aria-label="Primary" className={className}>
      <ul className="flex flex-col gap-1">
        {NAV_ITEMS.map((item) => {
          // "/app" itself must only match exactly (every other route also
          // starts with "/app"); every other destination also matches its
          // own nested detail routes (e.g. "/app/customers/[id]") so the
          // sidebar stays highlighted while drilled into a record.
          const isActive =
            item.path === "/app" ? pathname === item.path : pathname.startsWith(item.path);
          return (
            <li key={item.id}>
              <Link
                href={item.path}
                onClick={onNavigate}
                aria-current={isActive ? "page" : undefined}
                className={cn(
                  "flex items-center gap-2 rounded-md border-l-2 px-3 py-2 text-sm transition-colors",
                  isActive
                    ? "border-primary-500 bg-primary-50 text-primary-700 font-semibold"
                    : "text-text-secondary hover:bg-surface-2 hover:text-text-primary border-transparent font-medium",
                )}
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
