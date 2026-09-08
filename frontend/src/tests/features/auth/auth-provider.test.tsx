import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AuthProvider, useAuth } from "@/features/auth/auth-provider";
import { withAccessTokenRetry } from "@/lib/api/session";
import { apiClient } from "@/lib/api/client";
import { __setTimeoutOverrideForTests } from "@/lib/api/request";
import { FIXTURE_USER, mockState } from "@/tests/msw/handlers";

function Probe() {
  const auth = useAuth();
  return (
    <div>
      <p data-testid="status">{auth.status}</p>
      <p data-testid="user">{auth.user?.email ?? "none"}</p>
      <p data-testid="error">{auth.error?.code ?? "none"}</p>
      <p data-testid="logoutPending">{String(auth.logoutPending)}</p>
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

  it("C. a real 401 (no session at all) resolves to confirmed unauthenticated, not uncertain", async () => {
    // No mockState.refreshCookieValid set — the backend genuinely has no
    // session to offer, a definitive 401 "authentication_failed", not a
    // network problem. `error` must stay null: this is "not logged in", not
    // something a caller should offer a Retry action for.
    renderWithAuth();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
    expect(screen.getByTestId("error")).toHaveTextContent("none");
  });

  it("resolves to authenticated when a valid refresh session already exists", async () => {
    // Simulate an existing valid refresh cookie from a prior session, as if
    // the page were reloaded after a successful login.
    mockState.refreshCookieValid = true;

    renderWithAuth();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
    expect(screen.getByTestId("user")).toHaveTextContent(FIXTURE_USER.email);
  });

  it("A. initial bootstrap network error resolves to uncertain, never unauthenticated", async () => {
    mockState.refreshNetworkError = true;

    renderWithAuth();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("uncertain"));
    expect(screen.getByTestId("error")).toHaveTextContent("network_error");
    expect(screen.getByTestId("user")).toHaveTextContent("none");
  });

  it("B. initial bootstrap timeout resolves to uncertain", async () => {
    __setTimeoutOverrideForTests(50);
    mockState.refreshTimeout = true;

    renderWithAuth();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("uncertain"));
    expect(screen.getByTestId("error")).toHaveTextContent("timeout");
  });

  it("3B.A. refresh succeeds but /me/ hangs: bounded timeout, resolves to uncertain — no infinite loading, no login redirect", async () => {
    __setTimeoutOverrideForTests(50);
    mockState.refreshCookieValid = true;
    mockState.meHang = true;

    renderWithAuth();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("uncertain"));
    expect(screen.getByTestId("error")).toHaveTextContent("timeout");
    expect(screen.getByTestId("user")).toHaveTextContent("none");
  });

  it("E. an unexpected non-auth backend response (internal_server_error) during bootstrap resolves to uncertain, not unauthenticated", async () => {
    mockState.refreshInternalServerError = true;

    renderWithAuth();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("uncertain"));
    expect(screen.getByTestId("error")).toHaveTextContent("internal_server_error");
  });

  it("F. a malformed/unparseable backend response during bootstrap resolves to uncertain, not unauthenticated", async () => {
    mockState.refreshMalformedBody = true;

    renderWithAuth();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("uncertain"));
    expect(screen.getByTestId("error")).toHaveTextContent("parse_error");
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

  it("clears logout privileged UI even when the server logout call fails, and flags it unconfirmed", async () => {
    mockState.refreshCookieValid = true;
    const user = userEvent.setup();
    renderWithAuth();
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

    mockState.logoutNetworkError = true;
    await user.click(screen.getByRole("button", { name: "Logout" }));

    // Privileged UI is gone regardless of the server call's outcome...
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
    // ...but the app must not silently claim the server confirmed it.
    expect(screen.getByTestId("logoutPending")).toHaveTextContent("true");
  });

  it("does not flag logoutPending after a successful logout", async () => {
    mockState.refreshCookieValid = true;
    const user = userEvent.setup();
    renderWithAuth();
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

    await user.click(screen.getByRole("button", { name: "Logout" }));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
    expect(screen.getByTestId("logoutPending")).toHaveTextContent("false");
  });

  it("retries revocation on the next bootstrap instead of silently re-authenticating, and stops once it succeeds", async () => {
    // Simulate: user logged in, clicked logout, the request failed, and the
    // page was reloaded (a fresh AuthProvider mount) while still holding a
    // technically-valid refresh cookie.
    mockState.refreshCookieValid = true;
    mockState.logoutNetworkError = true;
    const first = renderWithAuth();
    await waitFor(() => expect(first.getByTestId("status")).toHaveTextContent("authenticated"));
    await userEvent.setup().click(first.getByRole("button", { name: "Logout" }));
    await waitFor(() => expect(first.getByTestId("logoutPending")).toHaveTextContent("true"));
    first.unmount();

    // Reload: the server is still unreachable — must stay unauthenticated,
    // not silently re-authenticate via the still-technically-valid cookie.
    const second = renderWithAuth();
    await waitFor(() => expect(second.getByTestId("status")).toHaveTextContent("unauthenticated"));
    expect(second.getByTestId("logoutPending")).toHaveTextContent("true");
    expect(second.getByTestId("user")).toHaveTextContent("none");
    second.unmount();

    // The network recovers; the next bootstrap's retry succeeds and clears
    // the pending flag.
    mockState.logoutNetworkError = false;
    const third = renderWithAuth();
    await waitFor(() => expect(third.getByTestId("logoutPending")).toHaveTextContent("false"));
    expect(third.getByTestId("status")).toHaveTextContent("unauthenticated");
  });

  it("clears a stale pending-logout marker on a fresh explicit login, and a reload stays authenticated (not re-triggered into revocation)", async () => {
    // Set up: a prior logout's revocation was never confirmed.
    mockState.refreshCookieValid = true;
    mockState.logoutNetworkError = true;
    const first = renderWithAuth();
    await waitFor(() => expect(first.getByTestId("status")).toHaveTextContent("authenticated"));
    await userEvent.setup().click(first.getByRole("button", { name: "Logout" }));
    await waitFor(() => expect(first.getByTestId("logoutPending")).toHaveTextContent("true"));
    first.unmount();

    // The user deliberately logs in again — a new, intentional session that
    // supersedes the old one's unconfirmed logout. Network recovers for this
    // fresh login (it isn't the earlier logout attempt).
    mockState.logoutNetworkError = false;
    const second = renderWithAuth();
    await waitFor(() => expect(second.getByTestId("status")).toHaveTextContent("unauthenticated"));
    await userEvent.setup().click(second.getByRole("button", { name: "Login" }));
    await waitFor(() => expect(second.getByTestId("status")).toHaveTextContent("authenticated"));
    expect(second.getByTestId("logoutPending")).toHaveTextContent("false");
    second.unmount();

    // Reload: the stale marker must not survive to retrigger a revocation
    // attempt against the brand-new session — bootstrap goes straight to the
    // normal authenticated path.
    const third = renderWithAuth();
    await waitFor(() => expect(third.getByTestId("status")).toHaveTextContent("authenticated"));
    expect(third.getByTestId("logoutPending")).toHaveTextContent("false");
    expect(third.getByTestId("user")).toHaveTextContent(FIXTURE_USER.email);
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
