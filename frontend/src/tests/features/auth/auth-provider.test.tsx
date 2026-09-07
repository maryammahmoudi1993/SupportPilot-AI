import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AuthProvider, useAuth } from "@/features/auth/auth-provider";
import { withAccessTokenRetry } from "@/lib/api/session";
import { apiClient } from "@/lib/api/client";
import { FIXTURE_USER, mockState } from "@/tests/msw/handlers";

function Probe() {
  const auth = useAuth();
  return (
    <div>
      <p data-testid="status">{auth.status}</p>
      <p data-testid="user">{auth.user?.email ?? "none"}</p>
      <p data-testid="error">{auth.error?.code ?? "none"}</p>
      <button
        onClick={() =>
          void auth.login({ email: FIXTURE_USER.email, password: FIXTURE_USER.password })
        }
      >
        Login
      </button>
      <button onClick={() => void auth.logout()}>Logout</button>
    </div>
  );
}

function renderWithAuth() {
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
}

describe("AuthProvider bootstrap", () => {
  it("starts in loading, then resolves to unauthenticated with no session", async () => {
    renderWithAuth();
    expect(screen.getByTestId("status")).toHaveTextContent("loading");

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
    expect(screen.getByTestId("user")).toHaveTextContent("none");
  });

  it("resolves to authenticated when a valid refresh session already exists", async () => {
    // Simulate an existing valid refresh cookie from a prior session, as if
    // the page were reloaded after a successful login.
    mockState.refreshCookieValid = true;

    renderWithAuth();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
    expect(screen.getByTestId("user")).toHaveTextContent(FIXTURE_USER.email);
  });

  it("surfaces a network-error classification without claiming authenticated", async () => {
    mockState.refreshNetworkError = true;

    renderWithAuth();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
    expect(screen.getByTestId("error")).toHaveTextContent("network_error");
  });
});

describe("AuthProvider login/logout", () => {
  it("transitions to authenticated on a successful login", async () => {
    const user = userEvent.setup();
    renderWithAuth();
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));

    await user.click(screen.getByRole("button", { name: "Login" }));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
    expect(screen.getByTestId("user")).toHaveTextContent(FIXTURE_USER.email);
  });

  it("transitions to unauthenticated and clears the user on logout", async () => {
    mockState.refreshCookieValid = true;
    const user = userEvent.setup();
    renderWithAuth();
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

    await user.click(screen.getByRole("button", { name: "Logout" }));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
    expect(screen.getByTestId("user")).toHaveTextContent("none");
  });

  it("clears logout privileged UI even when the server logout call fails", async () => {
    mockState.refreshCookieValid = true;
    const user = userEvent.setup();
    renderWithAuth();
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

    mockState.refreshNetworkError = true; // logout's own POST will fail the same way
    await user.click(screen.getByRole("button", { name: "Logout" }));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
  });

  it("transitions to unauthenticated when a background refresh fails mid-session", async () => {
    mockState.refreshCookieValid = true;
    renderWithAuth();
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

    // Simulate the refresh session having been revoked server-side, then a
    // protected call elsewhere in the app (not through AuthProvider)
    // discovering that via the normal 401 -> refresh -> fail flow.
    mockState.refreshCookieValid = false;
    mockState.forceMeUnauthorized = true;
    await act(async () => {
      await withAccessTokenRetry(() => apiClient.GET("/api/v1/auth/me/")).catch(() => {});
    });

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
    expect(screen.getByTestId("user")).toHaveTextContent("none");
  });
});
