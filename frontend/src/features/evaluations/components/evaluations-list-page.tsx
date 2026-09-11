"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import type { ReactNode } from "react";

import { EvaluationDatasetsTab } from "@/features/evaluations/components/evaluation-datasets-tab";
import { EvaluationRunsListSkeleton, EvaluationRunsTab } from "@/features/evaluations/components/evaluation-runs-tab";
import { canManageEvaluations } from "@/features/evaluations/types";
import {
  parseEvaluationDatasetListParams,
  parseEvaluationRunListParams,
  parseEvaluationTab,
} from "@/features/evaluations/url-params";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

function TabLink({ href, isActive, children }: { href: string; isActive: boolean; children: ReactNode }) {
  return (
    <Link
      href={href}
      aria-current={isActive ? "page" : undefined}
      className={cn(
        "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
        isActive
          ? "bg-primary-500 text-text-inverse"
          : "text-text-secondary hover:bg-surface-2 hover:text-text-primary",
      )}
    >
      {children}
    </Link>
  );
}

/**
 * `/app/evaluations` — Runs (default) and Datasets tabs (master prompt Part
 * C §10, mirroring features/knowledge/components/knowledge-list-page.tsx's
 * Documents/Sources tabs). Plain `<Link>`s with `aria-current`, not a JS
 * ARIA-tabs widget — same real-navigation-link reasoning documented there.
 * No Observability tab: there is no public tenant-facing Observability
 * resource to render (see frontend/README.md, "Evaluations").
 */
function EvaluationsListContent() {
  const workspace = useWorkspace();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const workspaceId = workspace.activeWorkspace?.id ?? null;
  const canManage = canManageEvaluations(workspace.activeWorkspace?.role);
  const tab = parseEvaluationTab(searchParams);
  const runParams = parseEvaluationRunListParams(searchParams);
  const datasetParams = parseEvaluationDatasetListParams(searchParams);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-text-primary text-xl font-semibold">Evaluations</h1>
        <p className="text-text-secondary text-sm">
          Real evaluation runs, results, and datasets for this workspace&apos;s agent
          versions — deterministic, offline scoring against recorded execution evidence.
        </p>
      </div>

      <nav aria-label="Evaluation views" className="flex gap-2">
        <TabLink href={pathname} isActive={tab === "runs"}>
          Runs
        </TabLink>
        <TabLink href={`${pathname}?tab=datasets`} isActive={tab === "datasets"}>
          Datasets
        </TabLink>
      </nav>

      {workspaceId === null ? (
        <EvaluationRunsListSkeleton />
      ) : tab === "datasets" ? (
        <EvaluationDatasetsTab workspaceId={workspaceId} params={datasetParams} canManage={canManage} />
      ) : (
        <EvaluationRunsTab workspaceId={workspaceId} params={runParams} />
      )}
    </div>
  );
}

export function EvaluationsListPage() {
  const workspace = useWorkspace();

  if (workspace.status !== "ready" || !workspace.activeWorkspace) {
    return (
      <div className="flex flex-1 items-center justify-center py-16">
        <Spinner label="Loading your workspace" />
      </div>
    );
  }

  return (
    <Suspense
      fallback={
        <div className="flex flex-1 items-center justify-center py-16">
          <Spinner label="Loading evaluations" />
        </div>
      }
    >
      <EvaluationsListContent />
    </Suspense>
  );
}
