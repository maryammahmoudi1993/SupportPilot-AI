import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AuthProvider, useAuth } from "@/features/auth/auth-provider";
import { SessionVerificationError } from "@/components/shell/session-verification-error";
import { mockState } from "@/tests/msw/handlers";

function Harness() {
  const auth = useAuth();
  return (
    <>
      <p data-testid="status">{auth.status}</p>
      <SessionVerificationError />
    </>
  );
}

function renderUncertain() {
  mockState.refreshNetworkError = true;
  return render(
    <AuthProvider>
      <Harness />
    </AuthProvider>,
  );
}

describe("SessionVerificationError", () => {
  it("has a semantic heading, explanatory text, and a Retry button — never claims the user is signed out", async () => {
    renderUncertain();
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("uncertain"));

    expect(
      screen.getByRole("heading", { name: "We couldn't verify your session" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/couldn't reach the server/i)).toBeInTheDocument();
    expect(screen.queryByText(/signed out/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("is fully keyboard-operable: Retry is reachable by Tab and activates on Enter", async () => {
    renderUncertain();
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("uncertain"));
    const user = userEvent.setup();

    await user.tab();
    expect(screen.getByRole("button", { name: "Retry" })).toHaveFocus();

    mockState.refreshNetworkError = false;
    mockState.refreshCookieValid = true;
    await user.keyboard("{Enter}");

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
  });

  it("Retry re-runs verification and restores authenticated status on success", async () => {
    renderUncertain();
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("uncertain"));

    mockState.refreshNetworkError = false;
    mockState.refreshCookieValid = true;
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
  });

  it("offers Sign out, reusing the existing logout flow (not a second implementation)", async () => {
    renderUncertain();
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("uncertain"));

    await userEvent.setup().click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
  });
});
