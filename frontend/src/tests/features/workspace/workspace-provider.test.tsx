import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AuthProvider, useAuth } from "@/features/auth/auth-provider";
import { WorkspaceProvider, useWorkspace } from "@/features/workspace/workspace-provider";
import { getStoredActiveWorkspaceId } from "@/features/workspace/storage";
import { apiClient } from "@/lib/api/client";
import { withAccessTokenRetry } from "@/lib/api/session";
import {
  FIXTURE_USER,
  FIXTURE_WORKSPACE_ACME,
  FIXTURE_WORKSPACE_GLOBEX,
  mockState,
} from "@/tests/msw/handlers";

function Probe() {
  const workspace = useWorkspace();
  return (
    <div>
      <p data-testid="status">{workspace.status}</p>
      <p data-testid="active">{workspace.activeWorkspace?.id ?? "none"}</p>
      <p data-testid="count">{workspace.workspaces.length}</p>
      {workspace.workspaces.map((w) => (
        <button key={w.id} onClick={() => workspace.selectWorkspace(w.id)}>
          Switch to {w.name}
        </button>
      ))}
      <button onClick={() => workspace.selectWorkspace("not-a-real-id")}>Switch to bogus</button>
    </div>
  );
}

function renderWithProviders() {
  return render(
    <AuthProvider>
      <WorkspaceProvider>
        <Probe />
      </WorkspaceProvider>
    </AuthProvider>,
  );
}

describe("WorkspaceProvider", () => {
  it("is idle while unauthenticated", async () => {
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("idle"));
    expect(screen.getByTestId("active")).toHaveTextContent("none");
  });

  it("loads the workspace list from the authenticated user and selects the first one", async () => {
    mockState.refreshCookieValid = true;
    FIXTURE_USER.workspaces = [FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX];

    renderWithProviders();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("ready"));
    expect(screen.getByTestId("count")).toHaveTextContent("2");
    await waitFor(() =>
      expect(screen.getByTestId("active")).toHaveTextContent(FIXTURE_WORKSPACE_ACME.id),
    );
  });

  it("reports an empty state for zero memberships, distinct from an error", async () => {
    mockState.refreshCookieValid = true;
    FIXTURE_USER.workspaces = [];

    renderWithProviders();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("empty"));
    expect(screen.getByTestId("active")).toHaveTextContent("none");
  });

  it("reports an error state (not empty) when the session can't be confirmed over the network", async () => {
    mockState.refreshNetworkError = true;

    renderWithProviders();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("error"));
  });

  it("switches the active workspace and persists the selection", async () => {
    mockState.refreshCookieValid = true;
    FIXTURE_USER.workspaces = [FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX];
    const user = userEvent.setup();
    renderWithProviders();
    await waitFor(() =>
      expect(screen.getByTestId("active")).toHaveTextContent(FIXTURE_WORKSPACE_ACME.id),
    );

    await user.click(
      screen.getByRole("button", { name: `Switch to ${FIXTURE_WORKSPACE_GLOBEX.name}` }),
    );

    await waitFor(() =>
      expect(screen.getByTestId("active")).toHaveTextContent(FIXTURE_WORKSPACE_GLOBEX.id),
    );
    expect(getStoredActiveWorkspaceId()).toBe(FIXTURE_WORKSPACE_GLOBEX.id);
  });

  it("ignores a switch request for a workspace ID that isn't in the caller's own membership list", async () => {
    mockState.refreshCookieValid = true;
    FIXTURE_USER.workspaces = [FIXTURE_WORKSPACE_ACME];
    const user = userEvent.setup();
    renderWithProviders();
    await waitFor(() =>
      expect(screen.getByTestId("active")).toHaveTextContent(FIXTURE_WORKSPACE_ACME.id),
    );

    await user.click(screen.getByRole("button", { name: "Switch to bogus" }));

    // No change, and nothing persisted for a workspace the user was never a member of.
    expect(screen.getByTestId("active")).toHaveTextContent(FIXTURE_WORKSPACE_ACME.id);
    expect(getStoredActiveWorkspaceId()).toBeNull();
  });

  it("restores a persisted selection that is still accessible", async () => {
    localStorage.setItem("sp_active_workspace_id", FIXTURE_WORKSPACE_GLOBEX.id);
    mockState.refreshCookieValid = true;
    FIXTURE_USER.workspaces = [FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX];

    renderWithProviders();

    await waitFor(() =>
      expect(screen.getByTestId("active")).toHaveTextContent(FIXTURE_WORKSPACE_GLOBEX.id),
    );
  });

  it("discards a persisted selection that is no longer accessible and falls back safely", async () => {
    localStorage.setItem("sp_active_workspace_id", "no-longer-a-member-here");
    mockState.refreshCookieValid = true;
    FIXTURE_USER.workspaces = [FIXTURE_WORKSPACE_ACME];

    renderWithProviders();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("ready"));
    await waitFor(() =>
      expect(screen.getByTestId("active")).toHaveTextContent(FIXTURE_WORKSPACE_ACME.id),
    );
    expect(getStoredActiveWorkspaceId()).toBeNull();
  });

  it("clears the active workspace when the session ends (logout)", async () => {
    mockState.refreshCookieValid = true;
    FIXTURE_USER.workspaces = [FIXTURE_WORKSPACE_ACME];

    render(
      <AuthProvider>
        <WorkspaceProvider>
          <LogoutButton />
          <Probe />
        </WorkspaceProvider>
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("ready"));

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Logout" }));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("idle"));
    expect(screen.getByTestId("active")).toHaveTextContent("none");
  });

  it("clears the active workspace when the session expires mid-app (not via the logout button)", async () => {
    mockState.refreshCookieValid = true;
    FIXTURE_USER.workspaces = [FIXTURE_WORKSPACE_ACME];

    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("ready"));

    // Simulate the refresh session having been revoked server-side, then a
    // protected call elsewhere in the app discovering that.
    mockState.refreshCookieValid = false;
    mockState.forceMeUnauthorized = true;
    await act(async () => {
      await withAccessTokenRetry(() => apiClient.GET("/api/v1/auth/me/")).catch(() => {});
    });

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("idle"));
    expect(screen.getByTestId("active")).toHaveTextContent("none");
  });
});

function LogoutButton() {
  const auth = useAuth();
  return <button onClick={() => void auth.logout()}>Logout</button>;
}
