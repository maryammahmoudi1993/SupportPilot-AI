import Link from "next/link";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * Safe "this specific record isn't available to you" state — used for a
 * confirmed 404, a route ID that fails basic format validation before any
 * request is made, and (by construction, since the backend returns 404 for
 * both) a resource that belongs to a different workspace. Deliberately
 * generic: it must never let a caller distinguish "doesn't exist" from
 * "exists in another workspace" (see backend/customers/selectors.py
 * `customer_get_for_workspace_or_404` and frontend/README.md, "Cross-
 * workspace resource handling").
 */
export function EntityNotFound({
  title,
  description,
  backHref,
  backLabel,
}: {
  title: string;
  description: string;
  backHref: string;
  backLabel: string;
}) {
  return (
    <Card className="mx-auto w-full max-w-md">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <Link
          href={backHref}
          className="bg-primary-500 text-text-inverse hover:bg-primary-600 inline-flex h-9 items-center justify-center rounded-md px-4 text-sm font-medium transition-colors"
        >
          {backLabel}
        </Link>
      </CardContent>
    </Card>
  );
}
