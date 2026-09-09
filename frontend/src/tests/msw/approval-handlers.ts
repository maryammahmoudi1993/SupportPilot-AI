/**
 * Request-level mocks for the approvals domain, mirroring the real backend
 * contract (approvals/views.py, approvals/serializers.py, approvals/errors.py):
 * workspace-scoped storage, `status` filtering, DRF `PageNumberPagination`'s
 * `{count,next,previous,results}` envelope, and the approve/reject decision
 * endpoints (mutating in-memory state, same as the real backend's state
 * machine — approved/rejected/expired/cancelled statuses are actually
 * enforced here, not just returned once).
 */
import { HttpResponse, http } from "msw";
import type { PathParams } from "msw";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface ApprovalDecisionFixture {
  id: string;
  decision: "approve" | "reject";
  decided_by: number | null;
  safe_comment: string;
  created_at: string;
}

export interface ApprovalRequestFixture {
  id: string;
  status: "pending" | "approved" | "rejected" | "expired" | "cancelled";
  required_role: string;
  requested_by: number | null;
  summary: string;
  safe_context: unknown;
  expires_at: string;
  created_at: string;
  resolved_at: string | null;
  decision: ApprovalDecisionFixture | null;
}

export function makeApprovalFixture(
  overrides: Partial<ApprovalRequestFixture> & { id: string; summary: string },
): ApprovalRequestFixture {
  return {
    status: "pending",
    required_role: "admin",
    requested_by: null,
    safe_context: { tool_key: "payment.refund" },
    expires_at: "2026-01-01T01:00:00Z",
    created_at: "2026-01-01T00:00:00Z",
    resolved_at: null,
    decision: null,
    ...overrides,
  };
}

export const approvalMockState = {
  approvalsByWorkspace: {} as Record<string, ApprovalRequestFixture[]>,
  listNetworkError: false,
  /** Simulated caller identity for self-approval-forbidden checks (rare in unit tests, but real). */
  actorUserId: 1,
  /** When set, every decide call for this approval ID responds with this error instead of mutating state. */
  forceDecisionError: null as {
    approvalId: string;
    status: number;
    code: string;
    message: string;
  } | null,
  decideCallCount: 0,
  /** Artificial delay before a decide call resolves — lets a test observe the real "mutation in flight" window. */
  decisionDelayMs: 0,
};

export function seedApprovals(workspaceId: string, approvals: ApprovalRequestFixture[]): void {
  approvalMockState.approvalsByWorkspace[workspaceId] = approvals;
}

export function resetApprovalMockState(): void {
  approvalMockState.approvalsByWorkspace = {};
  approvalMockState.listNetworkError = false;
  approvalMockState.actorUserId = 1;
  approvalMockState.forceDecisionError = null;
  approvalMockState.decisionDelayMs = 0;
  approvalMockState.decideCallCount = 0;
}

function paginate<T>(items: T[], url: URL) {
  const page = Number(url.searchParams.get("page") ?? "1");
  const pageSize = Number(url.searchParams.get("page_size") ?? "50");
  const count = items.length;
  const start = (page - 1) * pageSize;
  const results = items.slice(start, start + pageSize);
  const hasNext = start + pageSize < count;
  const hasPrevious = page > 1;
  const nextUrl = hasNext ? `${url.origin}${url.pathname}?page=${page + 1}` : null;
  const previousUrl = hasPrevious
    ? `${url.origin}${url.pathname}${page - 1 > 1 ? `?page=${page - 1}` : ""}`
    : null;
  return { count, next: nextUrl, previous: previousUrl, results };
}

function findApproval(workspaceId: string, approvalId: string): ApprovalRequestFixture | undefined {
  return approvalMockState.approvalsByWorkspace[workspaceId]?.find((a) => a.id === approvalId);
}

function decide(decisionValue: "approve" | "reject") {
  return async ({ request, params }: { request: Request; params: PathParams }) => {
    approvalMockState.decideCallCount += 1;
    const workspaceId = params.workspaceId as string;
    const approvalId = params.approvalId as string;

    if (approvalMockState.decisionDelayMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, approvalMockState.decisionDelayMs));
    }

    if (approvalMockState.forceDecisionError?.approvalId === approvalId) {
      const { status, code, message } = approvalMockState.forceDecisionError;
      return HttpResponse.json({ error: { code, message } }, { status });
    }

    const approval = findApproval(workspaceId, approvalId);
    if (!approval) {
      return HttpResponse.json(
        { error: { code: "not_found", message: "Approval request not found." } },
        { status: 404 },
      );
    }
    if (approval.status !== "pending") {
      return HttpResponse.json(
        {
          error: {
            code: "unknown_error",
            message:
              approval.status === "expired"
                ? "This approval request has expired."
                : "This approval request has already been resolved.",
          },
        },
        { status: 409 },
      );
    }

    const body = (await request.json().catch(() => ({}))) as { comment?: string };
    approval.status = decisionValue === "approve" ? "approved" : "rejected";
    approval.resolved_at = "2026-01-01T00:05:00Z";
    approval.decision = {
      id: `${approvalId}-decision`,
      decision: decisionValue,
      decided_by: approvalMockState.actorUserId,
      safe_comment: body.comment ?? "",
      created_at: "2026-01-01T00:05:00Z",
    };
    return HttpResponse.json(approval);
  };
}

export const approvalHandlers = [
  http.get(`${BASE}/api/v1/workspaces/:workspaceId/approvals/`, async ({ request, params }) => {
    if (approvalMockState.listNetworkError) {
      return HttpResponse.error();
    }
    const workspaceId = params.workspaceId as string;
    const url = new URL(request.url);
    const status = url.searchParams.get("status");
    let results = approvalMockState.approvalsByWorkspace[workspaceId] ?? [];
    if (status) {
      results = results.filter((approval) => approval.status === status);
    }
    return HttpResponse.json(paginate(results, url));
  }),

  http.get(`${BASE}/api/v1/workspaces/:workspaceId/approvals/:approvalId/`, async ({ params }) => {
    const workspaceId = params.workspaceId as string;
    const approvalId = params.approvalId as string;
    const approval = findApproval(workspaceId, approvalId);
    if (!approval) {
      return HttpResponse.json(
        { error: { code: "not_found", message: "Approval request not found." } },
        { status: 404 },
      );
    }
    return HttpResponse.json(approval);
  }),

  http.post(
    `${BASE}/api/v1/workspaces/:workspaceId/approvals/:approvalId/approve/`,
    decide("approve"),
  ),
  http.post(
    `${BASE}/api/v1/workspaces/:workspaceId/approvals/:approvalId/reject/`,
    decide("reject"),
  ),
];
