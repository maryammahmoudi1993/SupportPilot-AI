import { render } from "@testing-library/react";
import type { ReactElement } from "react";

import { AuthProvider } from "@/features/auth/auth-provider";
import { WorkspaceProvider } from "@/features/workspace/workspace-provider";
import { QueryProvider } from "@/lib/query/query-provider";

/** Mirrors the real provider nesting in app/(protected)/layout.tsx. */
export function renderAuthenticated(ui: ReactElement) {
  return render(
    <AuthProvider>
      <QueryProvider>
        <WorkspaceProvider>{ui}</WorkspaceProvider>
      </QueryProvider>
    </AuthProvider>,
  );
}
