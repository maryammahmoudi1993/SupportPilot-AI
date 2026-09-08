"use client";

import { useWorkspace } from "@/features/workspace/workspace-provider";
import { CheckIcon, ChevronsUpDownIcon } from "@/components/shell/icons";
import { Skeleton } from "@/components/ui/skeleton";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

const ROLE_LABELS: Record<string, string> = {
  owner: "Owner",
  admin: "Admin",
  support_manager: "Support Manager",
  support_agent: "Support Agent",
  viewer: "Viewer",
};

/**
 * Current-workspace display plus a switcher menu. Purely a UX affordance —
 * selecting a workspace here changes what the frontend *asks for*, never
 * what the backend *permits*; every request remains subject to full
 * server-side tenant/membership checks regardless of this component's state
 * (see frontend/README.md, "Workspace contract").
 */
export function WorkspaceSwitcher({ className }: { className?: string }) {
  const workspace = useWorkspace();

  if (workspace.status === "loading" || workspace.status === "idle") {
    return <Skeleton className={cn("h-9 w-44", className)} />;
  }

  if (workspace.status === "error") {
    return (
      <span className={cn("text-danger-700 text-sm", className)} role="status">
        Workspace unavailable
      </span>
    );
  }

  if (workspace.status === "empty") {
    return (
      <span className={cn("text-text-muted text-sm", className)} role="status">
        No workspace available
      </span>
    );
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className={cn(
            "border-border-default bg-surface-0 text-text-primary hover:bg-surface-2 flex h-9 max-w-56 items-center gap-2 rounded-md border px-3 text-sm font-medium",
            className,
          )}
        >
          <span className="truncate">{workspace.activeWorkspace?.name}</span>
          <ChevronsUpDownIcon className="text-text-muted h-4 w-4 shrink-0" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuLabel>Workspaces</DropdownMenuLabel>
        {workspace.workspaces.map((candidate) => (
          <DropdownMenuItem
            key={candidate.id}
            onSelect={() => workspace.selectWorkspace(candidate.id)}
            aria-current={candidate.id === workspace.activeWorkspace?.id ? "true" : undefined}
          >
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="truncate">{candidate.name}</span>
              <span className="text-text-muted text-xs">
                {ROLE_LABELS[candidate.role] ?? candidate.role}
              </span>
            </span>
            {candidate.id === workspace.activeWorkspace?.id && (
              <CheckIcon className="text-primary-500 h-4 w-4 shrink-0" />
            )}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
