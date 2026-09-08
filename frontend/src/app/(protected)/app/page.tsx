"use client";

import { useAuth } from "@/features/auth/auth-provider";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const ROLE_LABELS: Record<string, string> = {
  owner: "Owner",
  admin: "Admin",
  support_manager: "Support Manager",
  support_agent: "Support Agent",
  viewer: "Viewer",
};

/**
 * The real authenticated landing route. Shows only information the backend
 * actually returned — no ticket counts, SLA figures, resolution rates, or
 * other fabricated product metrics (see frontend/README.md, "Application
 * shell"). Business-domain pages (conversations, customers, tickets, ...)
 * are out of scope for Phase 18 and replace/extend this in later phases.
 */
export default function AppOverviewPage() {
  const auth = useAuth();
  const workspace = useWorkspace();

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4">
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <CardTitle>Overview</CardTitle>
            <Badge variant="primary">Frontend foundation</Badge>
          </div>
          <CardDescription>
            Signed in as {auth.user?.display_name ?? auth.user?.email}.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm">
          <div>
            <span className="text-text-muted">Account email</span>
            <p className="text-text-primary">{auth.user?.email}</p>
          </div>
          {workspace.activeWorkspace && (
            <>
              <div>
                <span className="text-text-muted">Active workspace</span>
                <p className="text-text-primary">{workspace.activeWorkspace.name}</p>
              </div>
              <div>
                <span className="text-text-muted">Your role</span>
                <p className="text-text-primary">
                  {ROLE_LABELS[workspace.activeWorkspace.role] ?? workspace.activeWorkspace.role}
                </p>
              </div>
            </>
          )}
          {workspace.status === "ready" && (
            <div>
              <span className="text-text-muted">Workspace memberships</span>
              <p className="text-text-primary">{workspace.workspaces.length}</p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
