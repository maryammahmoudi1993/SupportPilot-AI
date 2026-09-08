import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter } from "next/navigation";
import { describe, expect, it, vi } from "vitest";

import ProtectedLayout from "@/app/(protected)/layout";
import { AuthProvider } from "@/features/auth/auth-provider";
import { apiClient } from "@/lib/api/client";
import { __setTimeoutOverrideForTests } from "@/lib/api/request";
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

  it("redirects to /login on a confirmed absent session (no false 'signed out' claim needed, but no bounce needed either)", async () => {
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

  it("unmounts the shell and redirects when the session is CONFIRMED invalid mid-app", async () => {
    mockState.refreshCookieValid = true;
    FIXTURE_USER.workspaces = [FIXTURE_WORKSPACE_ACME];
    const replace = setupRouterMock();
    renderProtected();
    await waitFor(() => expect(screen.getByTestId("privileged-content")).toBeInTheDocument());

    // The refresh cookie itself was revoked server-side — /refresh/ will
    // reply with a definitive 401 authentication_failed, not a transport
    // failure.
    mockState.refreshCookieValid = false;
    mockState.forceMeUnauthorized = true;
    await act(async () => {
      await withAccessTokenRetry(() => apiClient.GET("/api/v1/auth/me/")).catch(() => {});
    });

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByTestId("privileged-content")).not.toBeInTheDocument();
  });

  it("A. initial bootstrap network failure: shows the session-verification UI, never redirects to /login, never renders the shell", async () => {
    mockState.refreshNetworkError = true;
    const replace = setupRouterMock();
    renderProtected();

    await waitFor(() =>
      expect(screen.getByText("We couldn't verify your session")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("privileged-content")).not.toBeInTheDocument();
    // Give any (unwanted) redirect effect a chance to fire before asserting it never did.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(replace).not.toHaveBeenCalled();
  });

  it("D. mid-session refresh network failure: session-verification UI replaces the shell, no login redirect", async () => {
    mockState.refreshCookieValid = true;
    FIXTURE_USER.workspaces = [FIXTURE_WORKSPACE_ACME];
    const replace = setupRouterMock();
    renderProtected();
    await waitFor(() => expect(screen.getByTestId("privileged-content")).toBeInTheDocument());

    mockState.refreshCookieValid = false; // irrelevant once the request itself fails on the network
    mockState.refreshNetworkError = true;
    mockState.forceMeUnauthorized = true;
    await act(async () => {
      await withAccessTokenRetry(() => apiClient.GET("/api/v1/auth/me/")).catch(() => {});
    });

    await waitFor(() =>
      expect(screen.getByText("We couldn't verify your session")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("privileged-content")).not.toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(replace).not.toHaveBeenCalled();
  });

  it("E. uncertain -> Retry -> valid session: app shell is restored", async () => {
    mockState.refreshNetworkError = true;
    setupRouterMock();
    renderProtected();
    await waitFor(() =>
      expect(screen.getByText("We couldn't verify your session")).toBeInTheDocument(),
    );

    mockState.refreshNetworkError = false;
    mockState.refreshCookieValid = true;
    FIXTURE_USER.workspaces = [FIXTURE_WORKSPACE_ACME];
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(screen.getByTestId("privileged-content")).toBeInTheDocument());
  });

  it("F. uncertain -> Retry -> confirmed invalid session: redirects to /login", async () => {
    mockState.refreshNetworkError = true;
    const replace = setupRouterMock();
    renderProtected();
    await waitFor(() =>
      expect(screen.getByText("We couldn't verify your session")).toBeInTheDocument(),
    );

    mockState.refreshNetworkError = false; // now the backend actually answers: no valid session
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });

  it("G. uncertain -> Retry -> network still down: remains uncertain, no redirect, no loop", async () => {
    mockState.refreshNetworkError = true;
    const replace = setupRouterMock();
    renderProtected();
    await waitFor(() =>
      expect(screen.getByText("We couldn't verify your session")).toBeInTheDocument(),
    );

    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));

    // Still uncertain — the retry itself also failed on the network.
    await waitFor(() =>
      expect(screen.getByText("We couldn't verify your session")).toBeInTheDocument(),
    );
    expect(replace).not.toHaveBeenCalled();
  });

  it("H. a hung /me/ (refresh succeeded) is bounded, resolves to uncertain, and Retry recovers to authenticated once /me/ answers", async () => {
    __setTimeoutOverrideForTests(50);
    mockState.refreshCookieValid = true;
    mockState.meHang = true;
    setupRouterMock();
    renderProtected();

    await waitFor(() =>
      expect(screen.getByText("We couldn't verify your session")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("privileged-content")).not.toBeInTheDocument();

    mockState.meHang = false;
    FIXTURE_USER.workspaces = [FIXTURE_WORKSPACE_ACME];
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(screen.getByTestId("privileged-content")).toBeInTheDocument());
  });

  it("redirects exactly once on a CONFIRMED invalid session, without looping", async () => {
    // (No refresh cookie at all — a definitive, not a transport, failure.)
    const replace = setupRouterMock();
    renderProtected();

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(replace).toHaveBeenCalledTimes(1);
  });
});
