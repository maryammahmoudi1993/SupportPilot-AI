import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter, useSearchParams } from "next/navigation";
import { describe, expect, it, vi } from "vitest";

import { AuthProvider } from "@/features/auth/auth-provider";
import { LoginForm } from "@/features/auth/login-form";
import { DEFAULT_REDIRECT_TARGET } from "@/features/auth/redirect";
import { FIXTURE_USER, mockState } from "@/tests/msw/handlers";

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

async function renderLoginForm(next: string | null = null) {
  const routerMocks = setupRouterMocks(next);
  render(
    <AuthProvider>
      <LoginForm />
    </AuthProvider>,
  );
  // AuthProvider's own bootstrap must settle first (it fires an unrelated
  // /me/ + /refresh/ round trip) so it can't race with the form's own calls.
  await waitFor(() => expect(mockState.meCallCount).toBeGreaterThan(0));
  return routerMocks;
}

function fillAndSubmit(email: string, password: string) {
  const user = userEvent.setup();
  return (async () => {
    await user.type(screen.getByLabelText("Email"), email);
    await user.type(screen.getByLabelText("Password"), password);
    await user.click(screen.getByRole("button", { name: "Sign in" }));
  })();
}

describe("LoginForm", () => {
  it("logs in successfully and redirects to the default target", async () => {
    const { replace } = await renderLoginForm();

    await fillAndSubmit(FIXTURE_USER.email, FIXTURE_USER.password);

    await waitFor(() => expect(replace).toHaveBeenCalledWith(DEFAULT_REDIRECT_TARGET));
  });

  it("redirects to a safe next target after login", async () => {
    const { replace } = await renderLoginForm("/tickets");

    await fillAndSubmit(FIXTURE_USER.email, FIXTURE_USER.password);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/tickets"));
  });

  it("falls back to the default target when next is an unsafe external URL", async () => {
    const { replace } = await renderLoginForm("https://evil.example");

    await fillAndSubmit(FIXTURE_USER.email, FIXTURE_USER.password);

    await waitFor(() => expect(replace).toHaveBeenCalledWith(DEFAULT_REDIRECT_TARGET));
  });

  it("shows a safe error message and does not authenticate on invalid credentials", async () => {
    const { replace } = await renderLoginForm();

    await fillAndSubmit(FIXTURE_USER.email, "wrong-password");

    expect(await screen.findByRole("alert")).toHaveTextContent(/incorrect email or password/i);
    expect(replace).not.toHaveBeenCalled();
    // The form must remain usable after a failed attempt.
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  it("shows a rate-limit message on 429, distinct from invalid credentials", async () => {
    await renderLoginForm();
    mockState.loginRateLimited = true;

    await fillAndSubmit(FIXTURE_USER.email, FIXTURE_USER.password);

    expect(await screen.findByRole("alert")).toHaveTextContent(/too many attempts/i);
  });

  it("shows a network-failure message when the request cannot reach the server", async () => {
    await renderLoginForm();
    mockState.loginNetworkError = true;

    await fillAndSubmit(FIXTURE_USER.email, FIXTURE_USER.password);

    expect(await screen.findByRole("alert")).toHaveTextContent(/unable to reach the server/i);
  });

  it("never logs the password to the console", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    await renderLoginForm();

    await fillAndSubmit(FIXTURE_USER.email, "a-very-secret-password");

    const allLoggedText = [...consoleSpy.mock.calls, ...errorSpy.mock.calls].flat().join(" ");
    expect(allLoggedText).not.toContain("a-very-secret-password");

    consoleSpy.mockRestore();
    errorSpy.mockRestore();
  });

  it("disables the submit button and ignores a rapid duplicate submission", async () => {
    await renderLoginForm();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Email"), FIXTURE_USER.email);
    await user.type(screen.getByLabelText("Password"), FIXTURE_USER.password);

    const button = screen.getByRole("button", { name: "Sign in" });
    // Fire two rapid clicks without awaiting between them.
    await Promise.all([user.click(button), user.click(button)]);

    await waitFor(() => expect(mockState.loginCallCount).toBe(1));
  });
});
