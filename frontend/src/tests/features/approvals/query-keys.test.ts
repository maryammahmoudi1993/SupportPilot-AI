import { describe, expect, it } from "vitest";

import { approvalKeys } from "@/features/approvals/query-keys";

describe("approvalKeys", () => {
  it("embeds the workspace ID as the second key segment for every key shape", () => {
    expect(approvalKeys.all("ws-a")).toEqual(["workspaces", "ws-a", "approvals"]);
    expect(approvalKeys.list("ws-a", { page: 1, status: "pending" })).toEqual([
      "workspaces",
      "ws-a",
      "approvals",
      "list",
      { page: 1, status: "pending" },
    ]);
    expect(approvalKeys.detail("ws-a", "appr-1")).toEqual([
      "workspaces",
      "ws-a",
      "approvals",
      "detail",
      "appr-1",
    ]);
  });

  it("produces disjoint list keys for two different workspaces given the same params", () => {
    const params = { page: 1, status: "pending" as const };
    expect(approvalKeys.list("ws-a", params)).not.toEqual(approvalKeys.list("ws-b", params));
  });

  it("produces disjoint detail keys for two different workspaces given the same approval ID", () => {
    expect(approvalKeys.detail("ws-a", "appr-1")).not.toEqual(
      approvalKeys.detail("ws-b", "appr-1"),
    );
  });
});
