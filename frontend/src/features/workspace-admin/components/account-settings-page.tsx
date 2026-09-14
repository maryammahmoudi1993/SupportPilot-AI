"use client";

import { useAuth } from "@/features/auth/auth-provider";
import { parseWorkspaceMemberships } from "@/features/workspace/parse";
import { SettingsNav } from "@/features/workspace-admin/components/settings-nav";
import { workspaceRoleLabel } from "@/features/workspace-admin/types";
import { Spinner } from "@/components/ui/spinner";

/**
 * The Account settings page (`/app/settings/account`, Phase 24 Chunk 3).
 *
 * Re-verified the entire account/security candidate space directly against
 * `main` before building anything (master prompt's contract-discovery-first
 * rule): `backend/accounts/urls.py` exposes exactly `login/`, `refresh/`,
 * `logout/`, `me/`, `csrf/` — no profile update, no password-change, no
 * session list/revoke/logout-all, no MFA, no email verification, no account
 * disable/delete endpoint exists anywhere in the backend (confirmed by
 * reading every URL config, not just `accounts/`; no `django-allauth`/
 * `dj-rest-auth` app is installed, and `django.contrib.auth`'s own
 * password-reset views are never wired into `config/urls.py`). `GET
 * /auth/me/` (`MeView`) is the only real, public account capability, and it
 * is GET-only — no `PATCH`/`PUT` exists on it.
 *
 * This page is therefore read-only by construction, not by an arbitrary
 * frontend choice: it renders the exact same `/me/` data `AuthProvider`
 * already fetched once at session bootstrap (no new network request, no
 * new query key) — the caller's own safe account fields (email, display
 * name) and their real workspace-membership summary (id/name/role per
 * workspace) via the same `parseWorkspaceMemberships` narrowing
 * `WorkspaceProvider` itself uses. See README.md, "Phase 24 — Account /
 * Security" for the full capability classification (what's real vs. N/A).
 */
export function AccountSettingsPage() {
  const auth = useAuth();

  // Deliberately does NOT gate on workspace readiness the way every other
  // /app/settings/* page does — this page's content (the caller's own
  // account fields and their real workspace-membership list) depends only
  // on `auth`, never on an *active* workspace being selected, so a
  // zero-workspace account still has a real, non-empty "no memberships"
  // answer here rather than an indefinite loading spinner. In real usage
  // this route is still reached only once the shared shell (`AppShell`'s
  // `WorkspaceGate`) has already resolved the workspace-load state for
  // every other reason any /app/* route needs it (sidebar/switcher); this
  // component just doesn't redundantly re-gate on top of that.
  if (auth.status !== "authenticated" || !auth.user) {
    return (
      <div className="flex flex-1 items-center justify-center py-16">
        <Spinner label="Loading your account" />
      </div>
    );
  }

  const memberships = parseWorkspaceMemberships(auth.user.workspaces ?? []);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-text-primary text-xl font-semibold">Account</h1>
        <p className="text-text-secondary text-sm">
          Your account details and workspace memberships. There is currently no way to change your
          email, password, or account settings from this application.
        </p>
      </div>

      <SettingsNav active="account" />

      <dl className="grid max-w-md grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
        <dt className="text-text-secondary font-medium">Display name</dt>
        <dd className="text-text-primary">{auth.user.display_name}</dd>
        <dt className="text-text-secondary font-medium">Email</dt>
        <dd className="text-text-primary">{auth.user.email}</dd>
      </dl>

      <div>
        <h2 className="text-text-primary text-sm font-semibold">Workspace memberships</h2>
        {memberships.length === 0 ? (
          <p className="text-text-secondary mt-1 text-sm">No workspace memberships.</p>
        ) : (
          <div className="border-border-subtle mt-2 overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[420px] text-left text-sm">
              <caption className="sr-only">
                Workspaces you are a member of, and your role in each
              </caption>
              <thead className="bg-surface-2 text-text-secondary text-xs font-medium uppercase">
                <tr>
                  <th scope="col" className="px-4 py-2.5">
                    Workspace
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Role
                  </th>
                </tr>
              </thead>
              <tbody className="divide-border-subtle divide-y">
                {memberships.map((membership) => (
                  <tr key={membership.id}>
                    <td className="px-4 py-2.5 font-medium">{membership.name}</td>
                    <td className="px-4 py-2.5">{workspaceRoleLabel(membership.role)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
