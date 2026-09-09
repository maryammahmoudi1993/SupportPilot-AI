import { describe, expect, it } from "vitest";

import {
  deriveApprovalContext,
  isTerminalToolExecutionStatus,
} from "@/features/tool-executions/types";
import type { ToolExecution } from "@/features/tool-executions/types";

function makeExecution(overrides: Partial<ToolExecution>): ToolExecution {
  return {
    id: "exec-1",
    agent_run_id: "run-1",
    tool_definition_id: "tool-1",
    tool_key: "demo.echo",
    status: "succeeded",
    idempotency_key: "",
    arguments_redacted: {},
    result_redacted: {},
    attempt_count: 1,
    timeout_seconds: 5,
    started_at: null,
    completed_at: null,
    error_code: "",
    error_message_safe: "",
    duration_ms: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as ToolExecution;
}

describe("isTerminalToolExecutionStatus", () => {
  it("classifies every real terminal status as terminal", () => {
    for (const status of [
      "succeeded",
      "failed",
      "timed_out",
      "cancelled",
      "blocked_by_policy",
      "approval_terminated",
    ] as const) {
      expect(isTerminalToolExecutionStatus(status)).toBe(true);
    }
  });

  it("classifies pending/running/waiting_for_approval as non-terminal", () => {
    for (const status of ["pending", "running", "waiting_for_approval"] as const) {
      expect(isTerminalToolExecutionStatus(status)).toBe(false);
    }
  });
});

describe("deriveApprovalContext", () => {
  it("returns none for a normal, never-gated execution", () => {
    expect(deriveApprovalContext(makeExecution({ status: "succeeded" }))).toEqual({
      kind: "none",
    });
  });

  it("returns waiting for waiting_for_approval", () => {
    expect(deriveApprovalContext(makeExecution({ status: "waiting_for_approval" }))).toEqual({
      kind: "waiting",
    });
  });

  it("returns blocked_by_policy for blocked_by_policy", () => {
    expect(deriveApprovalContext(makeExecution({ status: "blocked_by_policy" }))).toEqual({
      kind: "blocked_by_policy",
    });
  });

  it("derives the specific approval_terminated reason from error_code", () => {
    expect(
      deriveApprovalContext(
        makeExecution({ status: "approval_terminated", error_code: "approval_rejected" }),
      ),
    ).toEqual({ kind: "rejected" });
    expect(
      deriveApprovalContext(
        makeExecution({ status: "approval_terminated", error_code: "approval_expired" }),
      ),
    ).toEqual({ kind: "expired" });
    expect(
      deriveApprovalContext(
        makeExecution({ status: "approval_terminated", error_code: "approval_cancelled" }),
      ),
    ).toEqual({ kind: "cancelled" });
  });

  it("falls back safely for an approval_terminated execution with an unrecognized error_code", () => {
    expect(
      deriveApprovalContext(
        makeExecution({ status: "approval_terminated", error_code: "something_new" }),
      ),
    ).toEqual({ kind: "terminated_other" });
  });
});
