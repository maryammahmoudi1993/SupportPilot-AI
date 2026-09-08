"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import type { ReactNode } from "react";

import { useAuth } from "@/features/auth/auth-provider";
import { WorkspaceProvider } from "@/features/workspace/workspace-provider";
import { AppShell } from "@/components/shell/app-shell";
import { SessionVerificationError } from "@/components/shell/session-verification-error";
import { Spinner } from "@/components/ui/spinner";
import { QueryProvider } from "@/lib/query/query-provider";

/**
 * Gates every route under this group behind a confirmed session. This is a
 * UX convenience, not the security boundary — the backend enforces
 * authorization on every request regardless of what this layout does (see
 * frontend/README.md, "Protected routing"). Four states, matching
 * `AuthStatus` exactly:
 *
 * - "loading": render nothing privileged (a plain spinner) — never the
 *   shell, even briefly, while the session is still unconfirmed.
 * - "unauthenticated": redirect to /login — a *definitive* backend verdict
 *   of no valid session (also covers that verdict arriving while the user
 *   is already here — AuthProvider's transition to "unauthenticated"
 *   unmounts the shell on the next render, before this effect even fires).
 * - "uncertain": render `SessionVerificationError`, NOT a redirect to
 *   /login and NOT the shell. A network failure/timeout/unexpected
 *   response is not proof the session is invalid — see
 *   frontend/README.md, "Session state model" (Phase 18 Chunk 3A). This
 *   still removes all privileged content (it's not "authenticated" either),
 *   just without claiming the user is signed out.
 * - "authenticated": render the real shell, wrapped in WorkspaceProvider
 *   (workspace context is scoped to authenticated routes only, not the
 *   whole app — see features/workspace/workspace-provider.tsx).
 */
export default function ProtectedLayout({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const router = useRouter();

  useEffect(() => {
    // Only a *confirmed* invalid session redirects — "uncertain" must never
    // bounce to /login on the strength of a transport failure alone.
    if (auth.status === "unauthenticated") {
      router.replace("/login");
    }
  }, [auth.status, router]);

  if (auth.status === "loading") {
    return (
      <main id="main-content" className="flex min-h-screen items-center justify-center p-6">
        <Spinner label="Checking your session" />
      </main>
    );
  }

  if (auth.status === "uncertain") {
    return <SessionVerificationError />;
  }

  if (auth.status === "unauthenticated") {
    // Nothing privileged renders here either — the effect above is already
    // redirecting away. A brief, identical "checking your session" state
    // keeps this render pass free of any content that would have to be
    // torn down again a moment later.
    return (
      <main id="main-content" className="flex min-h-screen items-center justify-center p-6">
        <Spinner label="Checking your session" />
      </main>
    );
  }

  return (
    <QueryProvider>
      <WorkspaceProvider>
        <AppShell>{children}</AppShell>
      </WorkspaceProvider>
    </QueryProvider>
  );
}
