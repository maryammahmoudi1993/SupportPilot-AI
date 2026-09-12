"use client";

import Link from "next/link";
import { useState } from "react";
import type { FormEvent } from "react";

import {
  useAgentDefinitionOptionsQuery,
  useAgentVersionOptionsQuery,
} from "@/features/evaluations/queries";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Bounded "Start Run" input (Phase 23 Chunk 3): dataset is fixed by the page
 * context (this form only ever renders on one dataset's own detail page —
 * see evaluation-dataset-detail-page.tsx), so the only real choice an
 * operator makes here is which PUBLISHED agent version to evaluate against
 * — a coherent, bounded contract per the chunk spec, not an unbounded
 * free-form POST. `threshold_config` is deliberately not exposed as a form
 * field: it is free-form JSON with no fixed shape at the API layer (same
 * schema-gap reasoning as `StructuredPayload` elsewhere) and Chunk 3 does
 * not invent a structured threshold-builder UI for it — a run started here
 * always uses `{}` (no thresholds configured), a real and valid input the
 * backend accepts (`threshold_config: threshold_config or {}`).
 *
 * Two-step Agent -> Version select rather than a flat list: the backend has
 * no "list all published versions across all agents in this workspace"
 * endpoint (agents/urls.py only nests versions under one agent), so a flat
 * picker would require fetching every agent's versions up front. This is a
 * deliberate, documented UX/perf tradeoff, not a missing capability.
 */
export function StartEvaluationRunForm({
  workspaceId,
  isPending,
  error,
  onSubmit,
  onCancel,
}: {
  workspaceId: string;
  isPending: boolean;
  error: string | null;
  onSubmit: (agentVersionId: string) => void;
  onCancel: () => void;
}) {
  const [agentId, setAgentId] = useState<string>("");
  const [agentVersionId, setAgentVersionId] = useState<string>("");

  const agentsQuery = useAgentDefinitionOptionsQuery(workspaceId, true);
  const versionsQuery = useAgentVersionOptionsQuery(workspaceId, agentId || null, agentId !== "");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isPending || agentVersionId === "") {
      return;
    }
    onSubmit(agentVersionId);
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="border-border-subtle flex flex-col gap-3 rounded-lg border p-4"
      aria-label="Start a new evaluation run"
    >
      {agentsQuery.isPending && (
        <div role="status" aria-label="Loading agents">
          <Skeleton className="h-9 w-full" />
          <span className="sr-only">Loading agents</span>
        </div>
      )}
      {agentsQuery.isError && (
        <Alert variant="danger" title="Agents could not be loaded">
          {agentsQuery.error.message}
        </Alert>
      )}
      {agentsQuery.isSuccess && agentsQuery.data.length === 0 && (
        <Alert variant="info" title="No agents configured">
          This workspace has no agent definitions yet.{" "}
          <Link href="/app" className="underline">
            Configure an agent
          </Link>{" "}
          before starting an evaluation run.
        </Alert>
      )}
      {agentsQuery.isSuccess && agentsQuery.data.length > 0 && (
        <>
          <div>
            <Label htmlFor="eval-run-agent">Agent</Label>
            <select
              id="eval-run-agent"
              value={agentId}
              onChange={(event) => {
                setAgentId(event.target.value);
                setAgentVersionId("");
              }}
              disabled={isPending}
              className="bg-surface-0 text-text-primary border-border-default focus-visible:outline-primary-500 h-9 w-full rounded-md border px-3 text-sm outline-none"
            >
              <option value="">Select an agent…</option>
              {agentsQuery.data.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                </option>
              ))}
            </select>
          </div>

          {agentId !== "" && (
            <div>
              <Label htmlFor="eval-run-agent-version">Published version</Label>
              {versionsQuery.isPending && (
                <div role="status" aria-label="Loading agent versions">
                  <Skeleton className="h-9 w-full" />
                  <span className="sr-only">Loading agent versions</span>
                </div>
              )}
              {versionsQuery.isError && (
                <Alert variant="danger" title="Agent versions could not be loaded">
                  {versionsQuery.error.message}
                </Alert>
              )}
              {versionsQuery.isSuccess && versionsQuery.data.length === 0 && (
                <Alert variant="info" title="No published version">
                  This agent has no published version. Evaluation runs can only target a published
                  agent version.
                </Alert>
              )}
              {versionsQuery.isSuccess && versionsQuery.data.length > 0 && (
                <select
                  id="eval-run-agent-version"
                  value={agentVersionId}
                  onChange={(event) => setAgentVersionId(event.target.value)}
                  disabled={isPending}
                  className="bg-surface-0 text-text-primary border-border-default focus-visible:outline-primary-500 h-9 w-full rounded-md border px-3 text-sm outline-none"
                >
                  <option value="">Select a version…</option>
                  {versionsQuery.data.map((version) => (
                    <option key={version.id} value={version.id}>
                      v{version.version}
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}
        </>
      )}

      {error && (
        <Alert variant="danger" title="This evaluation run could not be started">
          {error}
        </Alert>
      )}

      <div className="flex gap-2">
        <Button
          type="submit"
          size="sm"
          disabled={isPending || agentVersionId === ""}
          isLoading={isPending}
        >
          Start run
        </Button>
        <Button type="button" variant="secondary" size="sm" onClick={onCancel} disabled={isPending}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
