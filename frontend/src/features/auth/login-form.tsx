"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useId, useState } from "react";
import type { FormEvent } from "react";

import { useAuth } from "@/features/auth/auth-provider";
import { resolveRedirectTarget } from "@/features/auth/redirect";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api/errors";

function messageForError(error: ApiError): string {
  switch (error.code) {
    case "authentication_failed":
      return "Incorrect email or password.";
    case "rate_limited": {
      const retryAfter =
        typeof error.details?.retry_after === "number" ? error.details.retry_after : null;
      return retryAfter
        ? `Too many attempts. Please try again in about ${retryAfter} seconds.`
        : "Too many attempts. Please wait a moment and try again.";
    }
    case "network_error":
      return "Unable to reach the server. Check your connection and try again.";
    case "timeout":
      return "The request took too long. Please try again.";
    case "validation_error":
      return "Enter a valid email and password.";
    default:
      return "Something went wrong. Please try again.";
  }
}

export function LoginForm() {
  const auth = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const emailId = useId();
  const passwordId = useId();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isSubmitting) {
      // A rapid double-click/double-Enter on the same tick both trigger this
      // handler before React re-renders the disabled button — this guard is
      // what actually stops the second submission, not just the disabled
      // attribute.
      return;
    }

    setIsSubmitting(true);
    setError(null);
    try {
      await auth.login({ email, password });
      const target = resolveRedirectTarget(searchParams.get("next"));
      router.replace(target);
    } catch (err) {
      setError(
        err instanceof ApiError ? messageForError(err) : "Something went wrong. Please try again.",
      );
      setIsSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
      {error && <Alert variant="danger">{error}</Alert>}

      <div>
        <Label htmlFor={emailId}>Email</Label>
        <Input
          id={emailId}
          name="email"
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={isSubmitting}
          invalid={Boolean(error)}
        />
      </div>

      <div>
        <Label htmlFor={passwordId}>Password</Label>
        <Input
          id={passwordId}
          name="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          disabled={isSubmitting}
          invalid={Boolean(error)}
        />
      </div>

      <Button type="submit" isLoading={isSubmitting} className="mt-2">
        Sign in
      </Button>
    </form>
  );
}
