import { describe, expect, it } from "vitest";

import { evaluationKeys } from "@/features/evaluations/query-keys";
import {
  DEFAULT_EVALUATION_RESULT_LIST_PARAMS,
  DEFAULT_EVALUATION_RUN_LIST_PARAMS,
} from "@/features/evaluations/types";

describe("evaluationKeys", () => {
  it("embeds the workspace ID as the second key segment for every key shape", () => {
    expect(evaluationKeys.all("ws-a")).toEqual(["workspaces", "ws-a", "evaluations"]);
    expect(evaluationKeys.runDetail("ws-a", "run-1")).toEqual([
      "workspaces",
      "ws-a",
      "evaluations",
      "runs",
      "detail",
      "run-1",
    ]);
    expect(evaluationKeys.results("ws-a", "run-1")).toEqual([
      "workspaces",
      "ws-a",
      "evaluations",
      "runs",
      "detail",
      "run-1",
      "results",
    ]);
  });

  it("produces disjoint run-list keys for two different workspaces given identical params", () => {
    const keyA = evaluationKeys.runList("ws-a", DEFAULT_EVALUATION_RUN_LIST_PARAMS);
    const keyB = evaluationKeys.runList("ws-b", DEFAULT_EVALUATION_RUN_LIST_PARAMS);
    expect(keyA).not.toEqual(keyB);
  });

  it("produces disjoint run-detail/results keys for the same run ID across two workspaces", () => {
    expect(evaluationKeys.runDetail("ws-a", "run-1")).not.toEqual(
      evaluationKeys.runDetail("ws-b", "run-1"),
    );
    expect(evaluationKeys.results("ws-a", "run-1")).not.toEqual(
      evaluationKeys.results("ws-b", "run-1"),
    );
  });

  it("produces disjoint run-list keys for two different status filters in the same workspace", () => {
    const keyA = evaluationKeys.runList("ws-a", {
      ...DEFAULT_EVALUATION_RUN_LIST_PARAMS,
      status: "running",
    });
    const keyB = evaluationKeys.runList("ws-a", {
      ...DEFAULT_EVALUATION_RUN_LIST_PARAMS,
      status: "failed",
    });
    expect(keyA).not.toEqual(keyB);
  });

  it("produces disjoint result-list keys for two different passed filters on the same run", () => {
    const keyA = evaluationKeys.resultList("ws-a", "run-1", {
      ...DEFAULT_EVALUATION_RESULT_LIST_PARAMS,
      passed: "passed",
    });
    const keyB = evaluationKeys.resultList("ws-a", "run-1", {
      ...DEFAULT_EVALUATION_RESULT_LIST_PARAMS,
      passed: "failed",
    });
    expect(keyA).not.toEqual(keyB);
  });
});
