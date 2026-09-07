"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { useAuth } from "@/features/auth/auth-provider";
import { parseWorkspaceMemberships } from "@/features/workspace/parse";
import {
  clearStoredActiveWorkspaceId,
  getStoredActiveWorkspaceId,
  setStoredActiveWorkspaceId,
} from "@/features/workspace/storage";
import type { WorkspaceMembershipSummary } from "@/features/workspace/types";
import type { ApiError } from "@/lib/api/errors";

/**
 * "idle" — not authenticated (or auth hasn't resolved that far yet): there
 * is nothing to load, and this is distinct from "loading" or "error" so a
 * consumer never has to infer "not logged in" from an empty array.
 * "error" — the *session itself* couldn't be confirmed (a network/timeout
 * failure surfaced by AuthProvider — see its `error` field), so the
 * workspace list is unknown, not empty; never render "you have no
 * workspaces" for this case (see Part 34 of the Chunk 3 spec).
 * "empty" — the session is confirmed and the user genuinely has zero active
 * workspace memberships.
 * "ready" — at least one workspace is available; `activeWorkspace` is set.
 */
export type WorkspaceStatus = "idle" | "loading" | "error" | "empty" | "ready";

export interface WorkspaceState {
  status: WorkspaceStatus;
  workspaces: WorkspaceMembershipSummary[];
  activeWorkspace: WorkspaceMembershipSummary | null;
  error: ApiError | null;
}

export interface WorkspaceContextValue extends WorkspaceState {
  /** No-ops if `workspaceId` isn't one of the caller's own accessible workspaces. */
  selectWorkspace: (workspaceId: string) => void;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const [activeWorkspaceId, setActiveWorkspaceId] = useState<string | null>(null);

  // The membership list's own authority is the current /me/ response
  // (already fetched by AuthProvider) — never a second network round trip,
  // and never anything invented client-side (see README.md, "Workspace
  // contract"). `parseWorkspaceMemberships` narrows the one field the
  // generated OpenAPI types can't describe; malformed entries are dropped,
  // never trusted.
  const workspaces = useMemo(
    () =>
      auth.status === "authenticated" ? parseWorkspaceMemberships(auth.user?.workspaces ?? []) : [],
    [auth.status, auth.user],
  );

  // Choose/repair the active workspace whenever the authoritative list
  // changes: keep the current selection if it's still valid; otherwise
  // restore a previously-persisted selection if it's still accessible;
  // otherwise fall back to the first server-provided workspace; discard a
  // persisted ID that no longer resolves (removed mid-session, revoked
  // membership, or left over from a different account on this browser)
  // rather than silently keep using it or send a request scoped to it.
  useEffect(() => {
    if (auth.status !== "authenticated") {
      // Synchronizing local selection state with an external system's state
      // (AuthProvider's session status) — the same justified pattern as
      // AuthProvider's own bootstrap effect (see its doc comment).
      setActiveWorkspaceId(null); // eslint-disable-line react-hooks/set-state-in-effect
      return;
    }
    setActiveWorkspaceId((current) => {
      if (current && workspaces.some((workspace) => workspace.id === current)) {
        return current;
      }
      const stored = getStoredActiveWorkspaceId();
      if (stored && workspaces.some((workspace) => workspace.id === stored)) {
        return stored;
      }
      if (stored) {
        clearStoredActiveWorkspaceId();
      }
      return workspaces[0]?.id ?? null;
    });
  }, [auth.status, workspaces]);

  const selectWorkspace = useCallback(
    (workspaceId: string) => {
      if (!workspaces.some((workspace) => workspace.id === workspaceId)) {
        return;
      }
      setActiveWorkspaceId(workspaceId);
      setStoredActiveWorkspaceId(workspaceId);
    },
    [workspaces],
  );

  const activeWorkspace =
    workspaces.find((workspace) => workspace.id === activeWorkspaceId) ?? null;

  let status: WorkspaceStatus;
  if (auth.status === "loading") {
    status = "loading";
  } else if (auth.error) {
    status = "error";
  } else if (auth.status !== "authenticated") {
    status = "idle";
  } else if (workspaces.length === 0) {
    status = "empty";
  } else {
    status = "ready";
  }

  const value = useMemo<WorkspaceContextValue>(
    () => ({ status, workspaces, activeWorkspace, error: auth.error, selectWorkspace }),
    [status, workspaces, activeWorkspace, auth.error, selectWorkspace],
  );

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) {
    throw new Error("useWorkspace() must be used within a <WorkspaceProvider>.");
  }
  return ctx;
}
