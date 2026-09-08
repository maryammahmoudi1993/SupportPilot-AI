import Link from "next/link";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function NotFound() {
  return (
    <main className="flex flex-1 items-center justify-center p-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Page not found</CardTitle>
          <CardDescription>
            The page you&apos;re looking for doesn&apos;t exist or may have moved.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Link
            href="/"
            className="bg-primary-500 text-text-inverse hover:bg-primary-600 inline-flex h-9 items-center justify-center rounded-md px-4 text-sm font-medium transition-colors"
          >
            Go back home
          </Link>
        </CardContent>
      </Card>
    </main>
  );
}
