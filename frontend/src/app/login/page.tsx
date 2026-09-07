"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";

import { useAuth } from "@/features/auth/auth-provider";
import { LoginForm } from "@/features/auth/login-form";
import { resolveRedirectTarget } from "@/features/auth/redirect";
import { Alert } from "@/components/ui/alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";

function LoginPageContent() {
  const auth = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (auth.status === "authenticated") {
      router.replace(resolveRedirectTarget(searchParams.get("next")));
    }
  }, [auth.status, router, searchParams]);

  if (auth.status === "loading" || auth.status === "authenticated") {
    // "authenticated" still renders this briefly while the redirect above
    // commits — never the login form for a session we already know is valid.
    return (
      <main className="flex flex-1 items-center justify-center p-6">
        <Spinner label="Checking your session" />
      </main>
    );
  }

  return (
    <main
      id="main-content"
      className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center gap-4 p-6"
    >
      {auth.logoutPending && (
        <Alert variant="warning" title="Sign-out not fully confirmed">
          You&apos;re signed out on this device, but we couldn&apos;t confirm it with the server.
          We&apos;ll keep trying automatically — or sign in again to replace the session.
        </Alert>
      )}
      <Card className="w-full">
        <CardHeader>
          <CardTitle>Sign in</CardTitle>
          <CardDescription>Sign in to your SupportPilot AI workspace.</CardDescription>
        </CardHeader>
        <CardContent>
          <LoginForm />
        </CardContent>
      </Card>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <main className="flex flex-1 items-center justify-center p-6">
          <Spinner label="Loading" />
        </main>
      }
    >
      <LoginPageContent />
    </Suspense>
  );
}
