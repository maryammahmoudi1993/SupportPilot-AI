import { describe, expect, it } from "vitest";

import { agentRunKeys } from "@/features/agent-runs/query-keys";
import { DEFAULT_AGENT_RUN_LIST_PARAMS } from "@/features/agent-runs/types";

describe("agentRunKeys", () => {
  it("embeds the workspace ID as the second key segment for every key shape", () => {
    expect(agentRunKeys.all("ws-a")).toEqual(["workspaces", "ws-a", "agent-runs"]);
    expect(agentRunKeys.detail("ws-a", "run-1")).toEqual([
      "workspaces",
      "ws-a",
      "agent-runs",
      "detail",
      "run-1",
    ]);
    expect(agentRunKeys.steps("ws-a", "run-1")).toEqual([
      "workspaces",
      "ws-a",
      "agent-runs",
      "detail",
      "run-1",
      "steps",
    ]);
  });

  it("produces disjoint list keys for two different workspaces given identical params", () => {
    const keyA = agentRunKeys.list("ws-a", DEFAULT_AGENT_RUN_LIST_PARAMS);
    const keyB = agentRunKeys.list("ws-b", DEFAULT_AGENT_RUN_LIST_PARAMS);
    expect(keyA).not.toEqual(keyB);
  });

  it("produces disjoint detail/steps keys for the same run ID across two workspaces", () => {
    expect(agentRunKeys.detail("ws-a", "run-1")).not.toEqual(agentRunKeys.detail("ws-b", "run-1"));
    expect(agentRunKeys.steps("ws-a", "run-1")).not.toEqual(agentRunKeys.steps("ws-b", "run-1"));
  });

  it("produces disjoint list keys for two different status filters in the same workspace", () => {
    const keyA = agentRunKeys.list("ws-a", { ...DEFAULT_AGENT_RUN_LIST_PARAMS, status: "running" });
    const keyB = agentRunKeys.list("ws-a", { ...DEFAULT_AGENT_RUN_LIST_PARAMS, status: "failed" });
    expect(keyA).not.toEqual(keyB);
  });
});
