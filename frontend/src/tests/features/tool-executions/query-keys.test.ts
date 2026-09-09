import { describe, expect, it } from "vitest";

import { toolExecutionKeys } from "@/features/tool-executions/query-keys";

describe("toolExecutionKeys", () => {
  it("embeds the workspace ID as the second key segment for every key shape", () => {
    expect(toolExecutionKeys.all("ws-a")).toEqual(["workspaces", "ws-a", "tool-executions"]);
    expect(toolExecutionKeys.forRun("ws-a", "run-1")).toEqual([
      "workspaces",
      "ws-a",
      "tool-executions",
      "for-run",
      "run-1",
    ]);
    expect(toolExecutionKeys.catalog("ws-a")).toEqual(["workspaces", "ws-a", "tools", "catalog"]);
  });

  it("produces disjoint forRun keys for two different workspaces given the same run ID", () => {
    expect(toolExecutionKeys.forRun("ws-a", "run-1")).not.toEqual(
      toolExecutionKeys.forRun("ws-b", "run-1"),
    );
  });

  it("produces disjoint forRun keys for two different runs in the same workspace", () => {
    expect(toolExecutionKeys.forRun("ws-a", "run-1")).not.toEqual(
      toolExecutionKeys.forRun("ws-a", "run-2"),
    );
  });

  it("produces disjoint catalog keys for two different workspaces", () => {
    expect(toolExecutionKeys.catalog("ws-a")).not.toEqual(toolExecutionKeys.catalog("ws-b"));
  });
});
