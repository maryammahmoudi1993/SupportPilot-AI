"use client";

import type { ReactNode } from "react";

import { useWorkspace } from "@/features/workspace/workspace-provider";
import { AlertTriangleIcon } from "@/components/shell/icons";
import { Header } from "@/components/shell/header";
import { Sidebar } from "@/components/shell/sidebar";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

/**
 * Owns app landmarks, the sidebar, the header, and the main content
 * container/skip-link target. Does not own any business-domain content —
 * every child route brings its own (see frontend/README.md, "Application
 * shell").
 */
export function AppShell({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header title={title} />
        <main id="main-content" className="flex-1 overflow-y-auto p-6">
          <WorkspaceGate>{children}</WorkspaceGate>
        </main>
      </div>
    </div>
  );
}

/**
 * Renders real page content only once a workspace is actually selected.
 * Zero-workspace and workspace-load-failure are distinct, intentional
 * states (Part 33/34 of the Chunk 3 spec) — neither is silently treated as
 * the other, and neither leaves stale privileged content on screen.
 */
function WorkspaceGate({ children }: { children: ReactNode }) {
  const workspace = useWorkspace();

  if (workspace.status === "loading" || workspace.status === "idle") {
    return (
      <div className="flex flex-1 items-center justify-center py-16">
        <Spinner label="Loading your workspace" />
      </div>
    );
  }

  if (workspace.status === "error") {
    return (
      <div className="mx-auto flex max-w-md flex-col items-center gap-3 py-16 text-center">
        <AlertTriangleIcon className="text-danger-500 h-8 w-8" />
        <p className="text-text-primary text-sm font-medium">Couldn&apos;t load your workspaces</p>
        <p className="text-text-secondary text-sm">
          We couldn&apos;t reach the server to confirm your workspace access. Check your connection
          and try again.
        </p>
        <Button variant="secondary" onClick={() => window.location.reload()}>
          Retry
        </Button>
      </div>
    );
  }

  if (workspace.status === "empty") {
    return (
      <div className="mx-auto flex max-w-md flex-col items-center gap-2 py-16 text-center">
        <p className="text-text-primary text-sm font-medium">
          No workspace is available for this account
        </p>
        <p className="text-text-secondary text-sm">
          Ask a workspace owner or admin to add this account as a member.
        </p>
      </div>
    );
  }

  return <>{children}</>;
}
