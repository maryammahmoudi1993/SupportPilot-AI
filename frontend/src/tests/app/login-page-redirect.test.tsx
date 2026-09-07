import { render, screen, waitFor } from "@testing-library/react";
import { useRouter, useSearchParams } from "next/navigation";
import { describe, expect, it, vi } from "vitest";

import LoginPage from "@/app/login/page";
import { AuthProvider } from "@/features/auth/auth-provider";
import { DEFAULT_REDIRECT_TARGET } from "@/features/auth/redirect";
import { mockState } from "@/tests/msw/handlers";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(),
  useSearchParams: vi.fn(),
}));

function setupRouterMocks(next: string | null = null) {
  const replace = vi.fn();
  vi.mocked(useRouter).mockReturnValue({ replace } as unknown as ReturnType<typeof useRouter>);
  vi.mocked(useSearchParams).mockReturnValue({
    get: (key: string) => (key === "next" ? next : null),
  } as unknown as ReturnType<typeof useSearchParams>);
  return { replace };
}

describe("LoginPage — already-authenticated redirect", () => {
  it("redirects an already-authenticated visitor away from /login instead of showing the form", async () => {
    mockState.refreshCookieValid = true;
    const { replace } = setupRouterMocks();

    render(
      <AuthProvider>
        <LoginPage />
      </AuthProvider>,
    );

    await waitFor(() => expect(replace).toHaveBeenCalledWith(DEFAULT_REDIRECT_TARGET));
    expect(screen.queryByRole("button", { name: "Sign in" })).not.toBeInTheDocument();
  });

  it("shows the login form (not a redirect) for an unauthenticated visitor", async () => {
    setupRouterMocks();

    render(
      <AuthProvider>
        <LoginPage />
      </AuthProvider>,
    );

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument(),
    );
  });
});
