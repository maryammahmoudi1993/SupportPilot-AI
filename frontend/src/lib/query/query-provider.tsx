"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import type { ReactNode } from "react";

import { createQueryClient } from "@/lib/query/query-client";

/**
 * Owns one `QueryClient` for the lifetime of an authenticated session.
 *
 * Mounted only inside `ProtectedLayout`, itself gated on `auth.status ===
 * "authenticated"` (see app/(protected)/layout.tsx) — so this component
 * unmounts entirely on logout/session-loss and remounts fresh on the next
 * login. That is what guarantees a signed-out (or newly-signed-in) session
 * never sees another session's cached server state: there's no cache to
 * leak because the `QueryClient` instance itself is gone, not merely
 * invalidated. Workspace switches, by contrast, happen *within* one
 * authenticated session and must not tear this down — cross-workspace
 * isolation there is the query key factories' job (every workspace-scoped
 * key embeds the workspace ID; see e.g. features/customers/query-keys.ts),
 * not this provider's.
 */
export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(() => createQueryClient());
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
