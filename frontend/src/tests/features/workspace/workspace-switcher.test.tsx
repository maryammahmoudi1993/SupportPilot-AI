import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AuthProvider } from "@/features/auth/auth-provider";
import { WorkspaceProvider } from "@/features/workspace/workspace-provider";
import { WorkspaceSwitcher } from "@/features/workspace/workspace-switcher";
import {
  FIXTURE_USER,
  FIXTURE_WORKSPACE_ACME,
  FIXTURE_WORKSPACE_GLOBEX,
  mockState,
} from "@/tests/msw/handlers";

function renderSwitcher() {
  return render(
    <AuthProvider>
      <WorkspaceProvider>
        <WorkspaceSwitcher />
      </WorkspaceProvider>
    </AuthProvider>,
  );
}

describe("WorkspaceSwitcher", () => {
  it("shows the current workspace name and lets the user switch to another, keyboard-operable", async () => {
    mockState.refreshCookieValid = true;
    FIXTURE_USER.workspaces = [FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX];
    const user = userEvent.setup();
    renderSwitcher();

    const trigger = await screen.findByRole("button", { name: FIXTURE_WORKSPACE_ACME.name });
    trigger.focus();
    await user.keyboard("{Enter}");

    const option = await screen.findByRole("menuitem", {
      name: new RegExp(FIXTURE_WORKSPACE_GLOBEX.name),
    });
    await user.click(option);

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: FIXTURE_WORKSPACE_GLOBEX.name }),
      ).toBeInTheDocument(),
    );
  });

  it("renders an empty state, not a broken switcher, for zero workspaces", async () => {
    mockState.refreshCookieValid = true;
    FIXTURE_USER.workspaces = [];
    renderSwitcher();

    await waitFor(() => expect(screen.getByText("No workspace available")).toBeInTheDocument());
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders an error state, distinct from empty, when the session can't be confirmed", async () => {
    mockState.refreshNetworkError = true;
    renderSwitcher();

    await waitFor(() => expect(screen.getByText("Workspace unavailable")).toBeInTheDocument());
  });
});
