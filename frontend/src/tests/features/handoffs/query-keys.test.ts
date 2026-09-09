import { describe, expect, it } from "vitest";

import { handoffKeys } from "@/features/handoffs/query-keys";

describe("handoffKeys", () => {
  it("embeds the workspace ID as the second key segment for every key shape", () => {
    expect(handoffKeys.all("ws-a")).toEqual(["workspaces", "ws-a", "handoffs"]);
    expect(handoffKeys.list("ws-a", { page: 1, status: "all" })).toEqual([
      "workspaces",
      "ws-a",
      "handoffs",
      "list",
      { page: 1, status: "all" },
    ]);
    expect(handoffKeys.detail("ws-a", "h-1")).toEqual([
      "workspaces",
      "ws-a",
      "handoffs",
      "detail",
      "h-1",
    ]);
    expect(handoffKeys.forConversation("ws-a", "conv-1")).toEqual([
      "workspaces",
      "ws-a",
      "handoffs",
      "list",
      "conversation",
      "conv-1",
    ]);
  });

  it("produces disjoint keys for two different workspaces given the same params", () => {
    expect(handoffKeys.detail("ws-a", "h-1")).not.toEqual(handoffKeys.detail("ws-b", "h-1"));
    expect(handoffKeys.forConversation("ws-a", "conv-1")).not.toEqual(
      handoffKeys.forConversation("ws-b", "conv-1"),
    );
  });
});
