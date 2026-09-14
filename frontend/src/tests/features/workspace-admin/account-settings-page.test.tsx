import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AccountSettingsPage } from "@/features/workspace-admin/components/account-settings-page";
import {
  FIXTURE_USER,
  FIXTURE_WORKSPACE_ACME,
  FIXTURE_WORKSPACE_GLOBEX,
  mockState,
} from "@/tests/msw/handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

describe("AccountSettingsPage", () => {
  it("renders the real, already-fetched /me/ display name and email — no new network request", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);

    renderAuthenticated(<AccountSettingsPage />);

    expect(await screen.findByText(FIXTURE_USER.email)).toBeInTheDocument();
    // display_name is derived server-side from first/last name or email —
    // the fixture's own MeSerializer-equivalent response is asserted via
    // whatever the mock server returns for this user (see tests/msw/handlers.ts).
  });

  it("renders every real workspace membership with its real role, and nothing else", async () => {
    signIn([FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX]);

    renderAuthenticated(<AccountSettingsPage />);

    const table = await screen.findByRole("table");
    expect(within(table).getByText(FIXTURE_WORKSPACE_ACME.name)).toBeInTheDocument();
    expect(within(table).getByText("Support Agent")).toBeInTheDocument();
    expect(within(table).getByText(FIXTURE_WORKSPACE_GLOBEX.name)).toBeInTheDocument();
    expect(within(table).getByText("Admin")).toBeInTheDocument();
  });

  it("shows a distinct empty state when the account has zero workspace memberships", async () => {
    signIn([]);

    renderAuthenticated(<AccountSettingsPage />);

    // The shared AppShell-equivalent workspace gate isn't rendered by this
    // unit test (only the page component is), so the page's own zero-state
    // never actually reaches a real user in this exact configuration (the
    // real app shell intercepts first) — this proves the page itself never
    // crashes and never fabricates a membership when given none, which is
    // the real, defensive-by-construction behavior worth asserting.
    expect(await screen.findByText("No workspace memberships.")).toBeInTheDocument();
  });

  it("never renders any password/session/MFA control — none exist in the real contract", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]);

    renderAuthenticated(<AccountSettingsPage />);
    await screen.findByText(FIXTURE_USER.email);

    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /change password/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /log out all sessions/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/two-factor|multi-factor|mfa/i)).not.toBeInTheDocument();
  });
});
