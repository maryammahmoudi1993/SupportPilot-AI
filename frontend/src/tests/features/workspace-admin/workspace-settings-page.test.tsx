import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { WorkspaceSettingsPage } from "@/features/workspace-admin/components/workspace-settings-page";
import {
  FIXTURE_USER,
  FIXTURE_WORKSPACE_ACME,
  FIXTURE_WORKSPACE_GLOBEX,
  mockState,
} from "@/tests/msw/handlers";
import {
  seedWorkspaceDetail,
  workspaceMemberMockState,
} from "@/tests/msw/workspace-member-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

describe("WorkspaceSettingsPage", () => {
  it("renders the real workspace name/slug/created date", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]); // admin
    seedWorkspaceDetail({
      id: FIXTURE_WORKSPACE_GLOBEX.id,
      name: "Globex Support",
      slug: "globex-support",
      is_active: true,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });

    renderAuthenticated(<WorkspaceSettingsPage />);

    expect(await screen.findByDisplayValue("Globex Support")).toBeInTheDocument();
    expect(screen.getByText("globex-support")).toBeInTheDocument();
  });

  it("shows a network-error state (not empty) and recovers via Retry", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    workspaceMemberMockState.workspaceDetailNetworkError = true;

    renderAuthenticated(<WorkspaceSettingsPage />);

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();

    workspaceMemberMockState.workspaceDetailNetworkError = false;
    seedWorkspaceDetail({
      id: FIXTURE_WORKSPACE_GLOBEX.id,
      name: "Globex Support",
      slug: "globex-support",
      is_active: true,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByDisplayValue("Globex Support")).toBeInTheDocument();
  });

  it("disables the name field and hides Save for a role without manage permission (support_agent)", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]); // support_agent
    seedWorkspaceDetail({
      id: FIXTURE_WORKSPACE_ACME.id,
      name: "Acme Support",
      slug: "acme-support",
      is_active: true,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });

    renderAuthenticated(<WorkspaceSettingsPage />);

    const input = await screen.findByDisplayValue("Acme Support");
    expect(input).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save changes" })).not.toBeInTheDocument();
  });

  it("an owner/admin can rename the workspace, and the server-authoritative name is reflected", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]); // admin
    seedWorkspaceDetail({
      id: FIXTURE_WORKSPACE_GLOBEX.id,
      name: "Globex Support",
      slug: "globex-support",
      is_active: true,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });

    renderAuthenticated(<WorkspaceSettingsPage />);

    const input = await screen.findByDisplayValue("Globex Support");
    const user = userEvent.setup();
    await user.clear(input);
    await user.type(input, "Globex Renamed");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(screen.getByText("Workspace name updated.")).toBeInTheDocument());
    expect(input).toHaveValue("Globex Renamed");
  });
});
