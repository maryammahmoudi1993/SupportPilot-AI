"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/features/auth/auth-provider";
import { DEFAULT_REDIRECT_TARGET } from "@/features/auth/redirect";
import { Spinner } from "@/components/ui/spinner";

/**
 * The root route never renders privileged content itself — it only decides
 * where to send the visitor once the session is known, so there is nothing
 * here that could flash before a redirect commits (see
 * frontend/README.md, "Protected routing").
 */
export default function RootPage() {
  const auth = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (auth.status === "authenticated") {
      router.replace(DEFAULT_REDIRECT_TARGET);
    } else if (auth.status === "unauthenticated") {
      router.replace("/login");
    }
  }, [auth.status, router]);

  return (
    <main id="main-content" className="flex flex-1 items-center justify-center p-6">
      <Spinner label="Loading" />
    </main>
  );
}
