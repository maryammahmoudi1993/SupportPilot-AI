import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * Temporary Phase 18 Chunk 1 placeholder.
 *
 * Authentication, workspace context, and the application shell land in
 * later chunks/phases — at that point this route becomes the real
 * authenticated landing page (or redirects to /login). This page exists
 * only to prove the framework, design tokens, and UI primitives render
 * correctly end to end.
 */
export default function Home() {
  return (
    <main id="main-content" className="mx-auto flex w-full max-w-2xl flex-1 items-center p-6">
      <Card className="w-full">
        <CardHeader>
          <div className="flex items-center gap-2">
            <CardTitle>SupportPilot AI</CardTitle>
            <Badge variant="primary">Frontend foundation</Badge>
          </div>
          <CardDescription>
            Application shell, authentication, and workspace context are not implemented yet.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-text-secondary text-sm">
          This build establishes the frontend framework, design system, and typed API transport
          foundation. Product screens are added in subsequent phases.
        </CardContent>
      </Card>
    </main>
  );
}
