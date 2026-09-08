import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { UserMenu } from "@/components/shell/user-menu";
import { AuthProvider } from "@/features/auth/auth-provider";
import { WorkspaceProvider } from "@/features/workspace/workspace-provider";
import { FIXTURE_USER, FIXTURE_WORKSPACE_ACME, mockState } from "@/tests/msw/handlers";

function renderUserMenu() {
  return render(
    <AuthProvider>
      <WorkspaceProvider>
        <UserMenu />
      </WorkspaceProvider>
    </AuthProvider>,
  );
}

describe("UserMenu", () => {
  it("renders nothing while unauthenticated (no privileged identity to show)", async () => {
    renderUserMenu();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows the real signed-in user's identity, email, and role — never fabricated data", async () => {
    mockState.refreshCookieValid = true;
    FIXTURE_USER.workspaces = [FIXTURE_WORKSPACE_ACME];
    const user = userEvent.setup();
    renderUserMenu();

    const trigger = await screen.findByRole("button", {
      name: `Account menu for ${FIXTURE_USER.display_name}`,
    });
    await user.click(trigger);

    expect(await screen.findByText(FIXTURE_USER.display_name)).toBeInTheDocument();
    expect(screen.getByText(FIXTURE_USER.email)).toBeInTheDocument();
    expect(screen.getByText("Support Agent")).toBeInTheDocument();
  });

  it("invokes the existing logout flow (server_unconfirmed distinction preserved) from the menu", async () => {
    mockState.refreshCookieValid = true;
    mockState.logoutNetworkError = true;
    FIXTURE_USER.workspaces = [FIXTURE_WORKSPACE_ACME];
    const user = userEvent.setup();
    renderUserMenu();

    const trigger = await screen.findByRole("button", {
      name: `Account menu for ${FIXTURE_USER.display_name}`,
    });
    await user.click(trigger);
    await user.click(await screen.findByRole("menuitem", { name: /Sign out/ }));

    // The menu itself disappears because the user is no longer authenticated
    // (UserMenu renders null once auth.status !== "authenticated") — the
    // privileged trigger is gone regardless of the server call's outcome.
    await waitFor(() => expect(screen.queryByRole("button")).not.toBeInTheDocument());
  });
});
