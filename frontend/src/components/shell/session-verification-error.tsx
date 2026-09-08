"use client";

import { useState } from "react";

import { useAuth } from "@/features/auth/auth-provider";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

/**
 * Rendered by `ProtectedLayout` whenever `AuthStatus === "uncertain"` —
 * the session could not be *verified* (network failure, timeout, an
 * unexpected backend response), as opposed to a definitive "no valid
 * session" verdict. This screen replaces the protected shell entirely (no
 * privileged content stays mounted behind it) but never claims the user is
 * signed out, and never triggers a `/login` redirect on its own — only an
 * explicit "Sign out" click does that, exactly like anywhere else in the
 * app (see frontend/README.md, "Session state model").
 */
export function SessionVerificationError() {
  const auth = useAuth();
  const [retrying, setRetrying] = useState(false);

  const handleRetry = async () => {
    setRetrying(true);
    try {
      await auth.revalidate();
    } finally {
      setRetrying(false);
    }
  };

  return (
    <main id="main-content" className="flex min-h-screen items-center justify-center p-6">
      <div className="flex w-full max-w-md flex-col items-center gap-4 text-center">
        <h1 className="text-text-primary text-lg font-semibold">
          We couldn&apos;t verify your session
        </h1>
        <Alert variant="warning" className="w-full text-left">
          Check your connection and try again. Your sign-in status hasn&apos;t changed — we simply
          couldn&apos;t reach the server to confirm it.
        </Alert>
        <div className="flex gap-2">
          <Button onClick={() => void handleRetry()} isLoading={retrying}>
            Retry
          </Button>
          <Button variant="secondary" onClick={() => void auth.logout()}>
            Sign out
          </Button>
        </div>
      </div>
    </main>
  );
}
