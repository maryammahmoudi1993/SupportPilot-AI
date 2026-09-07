"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/features/auth/auth-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";

/**
 * Temporary Phase 18 Chunk 2 placeholder: proves protected routing and auth
 * state, not the final dashboard. Workspace context and the real
 * application shell replace this in later chunks (see the doc comment on
 * LoginForm/AuthProvider and frontend/README.md, "Authentication").
 */
export default function Home() {
  const auth = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (auth.status === "unauthenticated") {
      router.replace("/login");
    }
  }, [auth.status, router]);

  if (auth.status === "loading" || auth.status === "unauthenticated") {
    // "unauthenticated" still renders this briefly while the redirect above
    // commits — never protected content for a session we know isn't valid.
    return (
      <main className="flex flex-1 items-center justify-center p-6">
        <Spinner label="Checking your session" />
      </main>
    );
  }

  return (
    <main id="main-content" className="mx-auto flex w-full max-w-2xl flex-1 items-center p-6">
      <Card className="w-full">
        <CardHeader>
          <div className="flex items-center gap-2">
            <CardTitle>SupportPilot AI</CardTitle>
            <Badge variant="primary">Frontend foundation</Badge>
          </div>
          <CardDescription>
            Signed in as {auth.user?.display_name ?? auth.user?.email}. Workspace context and the
            application shell are not implemented yet.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="secondary" onClick={() => void auth.logout()}>
            Sign out
          </Button>
        </CardContent>
      </Card>
    </main>
  );
}
