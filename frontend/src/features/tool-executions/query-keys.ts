/**
 * Typed, workspace-scoped query key factory for the tool-executions domain —
 * same policy as every other domain (see features/agent-runs/query-keys.ts):
 * every key embeds the workspace ID as its second segment, so a workspace
 * switch produces a disjoint cache entry, never a stale one another
 * workspace could render.
 *
 * `forRun` is nested under the run it belongs to (mirroring
 * `agentRunKeys.steps`) since every real use in this chunk is "the tool
 * executions for one Agent Run" — there is no standalone Tool Executions
 * list UI in Chunk 2 (see the build prompt Part I §26 decision, documented
 * in frontend/README.md). `catalog` is separate: one small, effectively
 * global (code-owned) list, not workspace-run-scoped data.
 */
export const toolExecutionKeys = {
  all: (workspaceId: string) => ["workspaces", workspaceId, "tool-executions"] as const,
  forRun: (workspaceId: string, runId: string) =>
    [...toolExecutionKeys.all(workspaceId), "for-run", runId] as const,
  catalog: (workspaceId: string) => ["workspaces", workspaceId, "tools", "catalog"] as const,
};
