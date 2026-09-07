import { act, render, screen, waitFor } from "@testing-library/react";
import { useRouter } from "next/navigation";
import { describe, expect, it, vi } from "vitest";

import ProtectedLayout from "@/app/(protected)/layout";
import { AuthProvider } from "@/features/auth/auth-provider";
import { apiClient } from "@/lib/api/client";
import { withAccessTokenRetry } from "@/lib/api/session";
import { FIXTURE_USER, FIXTURE_WORKSPACE_ACME, mockState } from "@/tests/msw/handlers";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(),
  usePathname: vi.fn(() => "/app"),
}));

function setupRouterMock() {
  const replace = vi.fn();
  vi.mocked(useRouter).mockReturnValue({ replace } as unknown as ReturnType<typeof useRouter>);
  return replace;
}

function renderProtected() {
  return render(
    <AuthProvider>
      <ProtectedLayout>
        <p data-testid="privileged-content">Privileged app content</p>
      </ProtectedLayout>
    </AuthProvider>,
  );
}

describe("ProtectedLayout", () => {
  it("never renders privileged content while the session is loading", () => {
    setupRouterMock();
    renderProtected();

    expect(screen.queryByTestId("privileged-content")).not.toBeInTheDocument();
    expect(screen.getByText("Checking your session")).toBeInTheDocument();
  });

  it("redirects to /login when there is no session", async () => {
    const replace = setupRouterMock();
    renderProtected();

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByTestId("privileged-content")).not.toBeInTheDocument();
  });

  it("renders the shell and children once authenticated", async () => {
    mockState.refreshCookieValid = true;
    FIXTURE_USER.workspaces = [FIXTURE_WORKSPACE_ACME];
    setupRouterMock();
    renderProtected();

    await waitFor(() => expect(screen.getByTestId("privileged-content")).toBeInTheDocument());
    // The shell itself: sidebar/header landmarks are present.
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
    expect(screen.getByRole("banner")).toBeInTheDocument();
  });

  it("unmounts the shell and redirects when the session expires mid-app", async () => {
    mockState.refreshCookieValid = true;
    FIXTURE_USER.workspaces = [FIXTURE_WORKSPACE_ACME];
    const replace = setupRouterMock();
    renderProtected();
    await waitFor(() => expect(screen.getByTestId("privileged-content")).toBeInTheDocument());

    mockState.refreshCookieValid = false;
    mockState.forceMeUnauthorized = true;
    await act(async () => {
      await withAccessTokenRetry(() => apiClient.GET("/api/v1/auth/me/")).catch(() => {});
    });

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByTestId("privileged-content")).not.toBeInTheDocument();
  });

  it("redirects exactly once on a temporary network failure, without looping", async () => {
    mockState.refreshNetworkError = true;
    const replace = setupRouterMock();
    renderProtected();

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    // Give any further (unwanted) effect runs a chance to fire before asserting call count.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(replace).toHaveBeenCalledTimes(1);
  });
});
