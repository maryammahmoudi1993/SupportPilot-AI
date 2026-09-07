"use client";

import { useAuth } from "@/features/auth/auth-provider";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { LogOutIcon } from "@/components/shell/icons";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

function initialsFor(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) {
    return "?";
  }
  const first = parts[0]?.[0] ?? "";
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? "") : "";
  return (first + last).toUpperCase();
}

const ROLE_LABELS: Record<string, string> = {
  owner: "Owner",
  admin: "Admin",
  support_manager: "Support Manager",
  support_agent: "Support Agent",
  viewer: "Viewer",
};

/**
 * Identity display plus sign-out. Every field here is a real value from
 * `/me/` (never a fabricated avatar image or placeholder metric) — see
 * frontend/README.md, "Application shell". Sign-out preserves the
 * complete/server_unconfirmed distinction from Chunk 2A: this menu never
 * claims a stronger guarantee than AuthProvider actually reports (the login
 * page surfaces `logoutPending`, not this menu — there is no privileged UI
 * left mounted here to show it in once sign-out completes locally).
 */
export function UserMenu() {
  const auth = useAuth();
  const workspace = useWorkspace();

  if (auth.status !== "authenticated" || !auth.user) {
    return null;
  }

  const displayName = auth.user.display_name || auth.user.email;
  const role = workspace.activeWorkspace?.role;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={`Account menu for ${displayName}`}
          className="border-border-default bg-surface-0 text-text-primary hover:bg-surface-2 flex h-9 w-9 items-center justify-center rounded-full border text-sm font-semibold"
        >
          {initialsFor(displayName)}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuLabel className="flex flex-col gap-0.5">
          <span className="text-text-primary text-sm font-medium">{displayName}</span>
          <span className="text-text-muted text-xs font-normal">{auth.user.email}</span>
          {role && (
            <span className="text-text-muted text-xs font-normal">{ROLE_LABELS[role] ?? role}</span>
          )}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void auth.logout()}>
          <LogOutIcon className="h-4 w-4" />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
