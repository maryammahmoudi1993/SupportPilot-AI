"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import type { ReactNode } from "react";

import { useAuth } from "@/features/auth/auth-provider";
import { WorkspaceProvider } from "@/features/workspace/workspace-provider";
import { AppShell } from "@/components/shell/app-shell";
import { Spinner } from "@/components/ui/spinner";

/**
 * Gates every route under this group behind a confirmed session. This is a
 * UX convenience, not the security boundary — the backend enforces
 * authorization on every request regardless of what this layout does (see
 * frontend/README.md, "Protected routing"). Three states only, matching
 * `AuthStatus` exactly:
 *
 * - "loading": render nothing privileged (a plain spinner) — never the
 *   shell, even briefly, while the session is still unconfirmed.
 * - "unauthenticated": redirect to /login (also covers a session that
 *   expires while the user is already here — AuthProvider's transition to
 *   "unauthenticated" unmounts the shell on the next render, before this
 *   effect even fires).
 * - "authenticated": render the real shell, wrapped in WorkspaceProvider
 *   (workspace context is scoped to authenticated routes only, not the
 *   whole app — see features/workspace/workspace-provider.tsx).
 */
export default function ProtectedLayout({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (auth.status === "unauthenticated") {
      router.replace("/login");
    }
  }, [auth.status, router]);

  if (auth.status !== "authenticated") {
    return (
      <main id="main-content" className="flex min-h-screen items-center justify-center p-6">
        <Spinner label="Checking your session" />
      </main>
    );
  }

  return (
    <WorkspaceProvider>
      <AppShell>{children}</AppShell>
    </WorkspaceProvider>
  );
}
