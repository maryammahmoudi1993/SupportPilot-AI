"use client";

import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * Global error boundary. Next.js renders this in place of the failed route
 * segment. It must be a Client Component. Never render `error.message` or
 * `error.stack` here — those can carry implementation detail that
 * shouldn't reach the browser in production.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Structured, safe client-side error log. Replace with a real
    // observability sink when one is wired up (later phase) — this must
    // never include the raw error message/stack in a rendered response.
    console.error("Unhandled route error", { digest: error.digest });
  }, [error]);

  return (
    <main className="flex flex-1 items-center justify-center p-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Something went wrong</CardTitle>
          <CardDescription>
            An unexpected error occurred. You can try again, or come back later if the problem
            continues.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={reset}>Try again</Button>
        </CardContent>
      </Card>
    </main>
  );
}
