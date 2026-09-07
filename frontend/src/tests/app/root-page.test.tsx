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
});
