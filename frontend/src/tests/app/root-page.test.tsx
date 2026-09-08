import { render, screen, waitFor } from "@testing-library/react";
import { useRouter } from "next/navigation";
import { describe, expect, it, vi } from "vitest";

import RootPage from "@/app/page";
import { AuthProvider } from "@/features/auth/auth-provider";
import { DEFAULT_REDIRECT_TARGET } from "@/features/auth/redirect";
import { mockState } from "@/tests/msw/handlers";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(),
}));

function setupRouterMock() {
  const replace = vi.fn();
  vi.mocked(useRouter).mockReturnValue({ replace } as unknown as ReturnType<typeof useRouter>);
  return replace;
}

describe("RootPage", () => {
  it("never renders privileged content itself while resolving", () => {
    setupRouterMock();
    render(
      <AuthProvider>
        <RootPage />
      </AuthProvider>,
    );
    expect(screen.getByText("Loading")).toBeInTheDocument();
  });

  it("redirects to /login when unauthenticated", async () => {
    const replace = setupRouterMock();
    render(
      <AuthProvider>
        <RootPage />
      </AuthProvider>,
    );

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });

  it("redirects to the default authenticated destination when a session already exists", async () => {
    mockState.refreshCookieValid = true;
    const replace = setupRouterMock();
    render(
      <AuthProvider>
        <RootPage />
      </AuthProvider>,
    );

    await waitFor(() => expect(replace).toHaveBeenCalledWith(DEFAULT_REDIRECT_TARGET));
  });

  it("G. renders SessionVerificationError (not an infinite spinner, not a /login redirect) when the session is uncertain", async () => {
    mockState.refreshNetworkError = true;
    const replace = setupRouterMock();
    render(
      <AuthProvider>
        <RootPage />
      </AuthProvider>,
    );

    await waitFor(() =>
      expect(screen.getByText("We couldn't verify your session")).toBeInTheDocument(),
    );
    expect(screen.queryByText("Loading")).not.toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(replace).not.toHaveBeenCalled();
  });
});
