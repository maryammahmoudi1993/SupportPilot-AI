import { act, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApprovalDetailPage } from "@/features/approvals/components/approval-detail-page";
import { APPROVAL_POLL_INTERVAL_MS } from "@/features/approvals/queries";
import { FIXTURE_USER, FIXTURE_WORKSPACE_GLOBEX, mockState } from "@/tests/msw/handlers";
import {
  approvalMockState,
  makeApprovalFixture,
  seedApprovals,
} from "@/tests/msw/approval-handlers";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

const APPROVAL_1 = "11111111-1111-4111-8111-111111111111";

function signIn() {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = [FIXTURE_WORKSPACE_GLOBEX];
}

describe("ApprovalDetailPage polling", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("polls the approval detail every interval while pending, picks up another operator's decision, and stops polling once terminal", async () => {
    signIn();
    seedApprovals(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeApprovalFixture({
        id: APPROVAL_1,
        summary: "x",
        required_role: "admin",
        status: "pending",
      }),
    ]);

    renderAuthenticated(<ApprovalDetailPage approvalId={APPROVAL_1} />);
    await screen.findByText("Pending");

    // Simulate another operator resolving it between polls.
    approvalMockState.approvalsByWorkspace[FIXTURE_WORKSPACE_GLOBEX.id][0].status = "approved";
    approvalMockState.approvalsByWorkspace[FIXTURE_WORKSPACE_GLOBEX.id][0].decision = {
      id: "d1",
      decision: "approve",
      decided_by: 42,
      safe_comment: "",
      created_at: "2026-01-01T00:05:00Z",
    };

    await act(async () => {
      await vi.advanceTimersByTimeAsync(APPROVAL_POLL_INTERVAL_MS + 100);
    });
    expect(await screen.findByText("Approved")).toBeInTheDocument();

    // If polling continued past the terminal state, the next tick would
    // pick this back up and flip the view back to "Pending" — it must not.
    approvalMockState.approvalsByWorkspace[FIXTURE_WORKSPACE_GLOBEX.id][0].status = "pending";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(APPROVAL_POLL_INTERVAL_MS * 3);
    });
    expect(screen.getByText("Approved")).toBeInTheDocument();
    expect(screen.queryByText("Pending")).not.toBeInTheDocument();
  });
});
