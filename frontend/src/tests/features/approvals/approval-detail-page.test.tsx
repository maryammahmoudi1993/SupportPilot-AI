import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { ApprovalDetailPage } from "@/features/approvals/components/approval-detail-page";
import {
  FIXTURE_USER,
  FIXTURE_WORKSPACE_ACME,
  FIXTURE_WORKSPACE_GLOBEX,
  mockState,
} from "@/tests/msw/handlers";
import {
  approvalMockState,
  makeApprovalFixture,
  seedApprovals,
} from "@/tests/msw/approval-handlers";
import { server } from "@/tests/msw/server";
import { renderAuthenticated } from "@/tests/support/render-authenticated";

const BASE = "http://localhost:8000";
const APPROVAL_1 = "11111111-1111-4111-8111-111111111111";

function signIn(workspaces: { id: string; name: string; slug: string; role: string }[]) {
  mockState.refreshCookieValid = true;
  FIXTURE_USER.workspaces = workspaces;
}

describe("ApprovalDetailPage", () => {
  it("renders a real pending approval's summary, required role, expiry, and frozen context", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedApprovals(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeApprovalFixture({
        id: APPROVAL_1,
        summary: "payment.refund: amount_minor=10000",
        required_role: "admin",
        safe_context: { tool_key: "payment.refund", arguments: { amount_minor: 10000 } },
      }),
    ]);

    renderAuthenticated(<ApprovalDetailPage approvalId={APPROVAL_1} />);

    expect(
      await screen.findByRole("heading", { name: "payment.refund: amount_minor=10000" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(screen.getByText("admin")).toBeInTheDocument();
    expect(screen.getByText(/"amount_minor": 10000/)).toBeInTheDocument();
  });

  it("shows Approve/Reject controls for a role that satisfies the requirement, and records a real approval", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]); // admin
    seedApprovals(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeApprovalFixture({ id: APPROVAL_1, summary: "x", required_role: "admin" }),
    ]);

    renderAuthenticated(<ApprovalDetailPage approvalId={APPROVAL_1} />);

    const approveButton = await screen.findByRole("button", { name: "Approve" });
    await userEvent.setup().click(approveButton);

    await waitFor(() => expect(screen.getByText("Approved")).toBeInTheDocument());
    expect(screen.getByText("approve")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
    expect(
      screen.getByText(/The related action may still be completing asynchronously/),
    ).toBeInTheDocument();
  });

  it("records a real rejection and reflects the server's persisted decision", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedApprovals(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeApprovalFixture({ id: APPROVAL_1, summary: "x", required_role: "admin" }),
    ]);

    renderAuthenticated(<ApprovalDetailPage approvalId={APPROVAL_1} />);

    const rejectButton = await screen.findByRole("button", { name: "Reject" });
    await userEvent.setup().click(rejectButton);

    await waitFor(() => expect(screen.getByText("Rejected")).toBeInTheDocument());
    expect(screen.getByText("reject")).toBeInTheDocument();
  });

  it("disables both Approve and Reject while a decision is in flight — never a double submit", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedApprovals(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeApprovalFixture({ id: APPROVAL_1, summary: "x", required_role: "admin" }),
    ]);
    // An artificial delay so the "mutation in flight" window is actually
    // observable, rather than racing a same-tick MSW resolution.
    approvalMockState.decisionDelayMs = 50;

    renderAuthenticated(<ApprovalDetailPage approvalId={APPROVAL_1} />);

    const approveButton = await screen.findByRole("button", { name: "Approve" });
    const rejectButton = screen.getByRole("button", { name: "Reject" });
    const user = userEvent.setup();
    // Fire both clicks without awaiting the first — proves a second click
    // during the in-flight window is inert, not just visually disabled.
    void user.click(approveButton);
    await waitFor(() => expect(approveButton).toBeDisabled());
    expect(rejectButton).toBeDisabled();
    await user.click(rejectButton); // inert: the button is disabled

    await waitFor(() => expect(screen.getByText("Approved")).toBeInTheDocument());
    expect(approvalMockState.decideCallCount).toBe(1);
  });

  it("does not show Approve/Reject for a role that does not satisfy the required role, and shows why", async () => {
    signIn([FIXTURE_WORKSPACE_ACME]); // support_agent
    seedApprovals(FIXTURE_WORKSPACE_ACME.id, [
      makeApprovalFixture({ id: APPROVAL_1, summary: "x", required_role: "support_manager" }),
    ]);

    renderAuthenticated(<ApprovalDetailPage approvalId={APPROVAL_1} />);

    await screen.findByText("Pending");
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
    expect(
      screen.getByText(/You do not have permission to decide this approval request/),
    ).toBeInTheDocument();
  });

  it("on a backend permission-denial, shows the real safe message and refetches — no state corruption", async () => {
    // Client-side role check would normally hide the buttons; force the
    // real backend 403 path anyway to prove defense-in-depth (a role that
    // changed server-side after this tab loaded).
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedApprovals(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeApprovalFixture({ id: APPROVAL_1, summary: "x", required_role: "admin" }),
    ]);
    approvalMockState.forceDecisionError = {
      approvalId: APPROVAL_1,
      status: 403,
      code: "approval_permission_denied",
      message: "You do not have permission to decide this approval request.",
    };

    renderAuthenticated(<ApprovalDetailPage approvalId={APPROVAL_1} />);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Approve" }));

    expect(
      await screen.findByText("You do not have permission to decide this approval request."),
    ).toBeInTheDocument();
    // The approval itself is still pending — no corrupted local state.
    expect(screen.getByText("Pending")).toBeInTheDocument();
  });

  it("on an already-decided conflict, refetches and shows the real terminal state instead of a catastrophic error", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    // Simulates the master prompt §9 scenario: this tab's view was fetched
    // while the request was still pending, but another operator resolved
    // it before this tab's decide call landed. The GET handler answers
    // "pending" once (this tab's stale initial load), then "approved"
    // forever after (the real state the onError refetch must pick up).
    let getCallCount = 0;
    server.use(
      http.get(`${BASE}/api/v1/workspaces/:workspaceId/approvals/:approvalId/`, () => {
        getCallCount += 1;
        const approved = getCallCount > 1;
        return HttpResponse.json(
          makeApprovalFixture({
            id: APPROVAL_1,
            summary: "x",
            required_role: "admin",
            status: approved ? "approved" : "pending",
            resolved_at: approved ? "2026-01-01T00:05:00Z" : null,
            decision: approved
              ? {
                  id: "d1",
                  decision: "approve",
                  decided_by: 99,
                  safe_comment: "",
                  created_at: "2026-01-01T00:05:00Z",
                }
              : null,
          }),
        );
      }),
    );
    approvalMockState.forceDecisionError = {
      approvalId: APPROVAL_1,
      status: 409,
      code: "approval_already_resolved",
      message: "This approval request has already been resolved.",
    };

    renderAuthenticated(<ApprovalDetailPage approvalId={APPROVAL_1} />);
    const approveButton = await screen.findByRole("button", { name: "Approve" });
    await userEvent.setup().click(approveButton);

    expect(
      await screen.findByText("This approval request has already been resolved."),
    ).toBeInTheDocument();
    // The onError refetch pulled the real (approved) row back — the stale
    // pending view is gone, replaced by the actual persisted decision.
    expect(await screen.findByText("Approved")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("renders terminal decision fields (outcome, decided-by, comment) for an already-resolved approval, with no controls", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedApprovals(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeApprovalFixture({
        id: APPROVAL_1,
        summary: "x",
        required_role: "admin",
        status: "rejected",
        resolved_at: "2026-01-01T00:05:00Z",
        decision: {
          id: "d1",
          decision: "reject",
          decided_by: 7,
          safe_comment: "Amount too high for this customer tier.",
          created_at: "2026-01-01T00:05:00Z",
        },
      }),
    ]);

    renderAuthenticated(<ApprovalDetailPage approvalId={APPROVAL_1} />);

    expect(await screen.findByText("Rejected")).toBeInTheDocument();
    expect(screen.getByText("reject")).toBeInTheDocument();
    expect(screen.getByText("User #7")).toBeInTheDocument();
    expect(screen.getByText("Amount too high for this customer tier.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
  });

  it("renders an expired approval as non-actionable, with no controls", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedApprovals(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeApprovalFixture({
        id: APPROVAL_1,
        summary: "x",
        required_role: "admin",
        status: "expired",
        resolved_at: "2026-01-01T01:00:00Z",
      }),
    ]);

    renderAuthenticated(<ApprovalDetailPage approvalId={APPROVAL_1} />);

    expect(await screen.findByText("Expired")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
  });

  it("renders an unrecognized future status safely instead of crashing, with no controls", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedApprovals(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeApprovalFixture({
        id: APPROVAL_1,
        summary: "x",
        required_role: "admin",
        status: "mystery_status" as never,
      }),
    ]);

    renderAuthenticated(<ApprovalDetailPage approvalId={APPROVAL_1} />);

    expect(await screen.findByText("mystery_status")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("never renders a value the backend redacted with ***REDACTED*** as anything but that literal marker", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);
    seedApprovals(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeApprovalFixture({
        id: APPROVAL_1,
        summary: "x",
        required_role: "admin",
        safe_context: { tool_key: "payment.refund", arguments: { api_key: "***REDACTED***" } },
      }),
    ]);

    renderAuthenticated(<ApprovalDetailPage approvalId={APPROVAL_1} />);

    expect(await screen.findByText(/\*\*\*REDACTED\*\*\*/)).toBeInTheDocument();
  });

  it("shows a safe not-found state for a confirmed 404", async () => {
    signIn([FIXTURE_WORKSPACE_GLOBEX]);

    renderAuthenticated(<ApprovalDetailPage approvalId="00000000-0000-4000-8000-000000000000" />);

    expect(await screen.findByText("Approval not found")).toBeInTheDocument();
  });

  it("shows a safe not-found state for an approval belonging to a different workspace — never leaked", async () => {
    signIn([FIXTURE_WORKSPACE_ACME, FIXTURE_WORKSPACE_GLOBEX]);
    seedApprovals(FIXTURE_WORKSPACE_GLOBEX.id, [
      makeApprovalFixture({ id: APPROVAL_1, summary: "Globex-only approval" }),
    ]);
    // Active workspace defaults to Acme; the approval above belongs to Globex.

    renderAuthenticated(<ApprovalDetailPage approvalId={APPROVAL_1} />);

    expect(await screen.findByText("Approval not found")).toBeInTheDocument();
    expect(screen.queryByText("Globex-only approval")).not.toBeInTheDocument();
  });
});
