/**
 * Request-level mocks for the agent-runs domain, mirroring the real backend
 * contract (agents/views.py, agents/selectors.py, agents/serializers.py):
 * workspace-scoped storage, `status` filtering, DRF `PageNumberPagination`'s
 * `{count,next,previous,results}` envelope, and the `{error:{code,message}}`
 * failure envelope. Same pattern as ticket-handlers.ts.
 */
import { HttpResponse, http } from "msw";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface AgentRunFixture {
  id: string;
  agent_version_id: string;
  agent_definition_id: string;
  conversation_id: string | null;
  ticket_id: string | null;
  trigger_message_id: string | null;
  output_message_id: string | null;
  trigger: string;
  status: string;
  input_message: string;
  input_metadata: Record<string, unknown>;
  final_response: string;
  started_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
  failure_code: string;
  failure_message_safe: string;
  model_call_count: number;
  step_count: number;
  tool_call_count: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_cost_usd: string | null;
  correlation_id: string;
  created_at: string;
  updated_at: string;
}

export interface AgentStepFixture {
  id: string;
  sequence: number;
  step_type: string;
  status: string;
  provider: string;
  model: string;
  input_summary: string;
  output_summary: string;
  safe_metadata: Record<string, unknown>;
  started_at: string | null;
  completed_at: string | null;
  latency_ms: number | null;
  error_code: string;
  created_at: string;
}

export function makeAgentRunFixture(
  overrides: Partial<AgentRunFixture> & { id: string; agent_version_id: string },
): AgentRunFixture {
  return {
    agent_definition_id: "00000000-0000-4000-8000-000000000000",
    conversation_id: null,
    ticket_id: null,
    trigger_message_id: null,
    output_message_id: null,
    trigger: "manual",
    status: "succeeded",
    input_message: "",
    input_metadata: {},
    final_response: "",
    started_at: "2026-01-01T00:00:00Z",
    completed_at: "2026-01-01T00:00:05Z",
    cancelled_at: null,
    failure_code: "",
    failure_message_safe: "",
    model_call_count: 1,
    step_count: 2,
    tool_call_count: 0,
    input_tokens: 10,
    output_tokens: 20,
    total_tokens: 30,
    estimated_cost_usd: null,
    correlation_id: "",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:05Z",
    ...overrides,
  };
}

export function makeAgentStepFixture(
  overrides: Partial<AgentStepFixture> & { id: string; sequence: number; step_type: string },
): AgentStepFixture {
  return {
    status: "succeeded",
    provider: "",
    model: "",
    input_summary: "",
    output_summary: "",
    safe_metadata: {},
    started_at: null,
    completed_at: null,
    latency_ms: null,
    error_code: "",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export const agentRunMockState = {
  runsByWorkspace: {} as Record<string, AgentRunFixture[]>,
  /** Which workspace owns a given run ID — for the cross-workspace 404 check. */
  runWorkspace: {} as Record<string, string>,
  stepsByRun: {} as Record<string, AgentStepFixture[]>,
  listNetworkError: false,
  detailNetworkError: false,
  listCallCount: 0,
  detailCallCount: 0,
};

export function seedAgentRuns(workspaceId: string, runs: AgentRunFixture[]): void {
  agentRunMockState.runsByWorkspace[workspaceId] = runs;
  for (const run of runs) {
    agentRunMockState.runWorkspace[run.id] = workspaceId;
  }
}

export function seedAgentSteps(runId: string, steps: AgentStepFixture[]): void {
  agentRunMockState.stepsByRun[runId] = steps;
}

export function resetAgentRunMockState(): void {
  agentRunMockState.runsByWorkspace = {};
  agentRunMockState.runWorkspace = {};
  agentRunMockState.stepsByRun = {};
  agentRunMockState.listNetworkError = false;
  agentRunMockState.detailNetworkError = false;
  agentRunMockState.listCallCount = 0;
  agentRunMockState.detailCallCount = 0;
}

function notFound() {
  return HttpResponse.json(
    { error: { code: "not_found", message: "Agent run not found." } },
    { status: 404 },
  );
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

export const agentRunHandlers = [
  http.get(`${BASE}/api/v1/workspaces/:workspaceId/agent-runs/`, async ({ request, params }) => {
    agentRunMockState.listCallCount += 1;

    if (agentRunMockState.listNetworkError) {
      return HttpResponse.error();
    }

    const workspaceId = params.workspaceId as string;
    const url = new URL(request.url);
    const status = url.searchParams.get("status");

    let results = agentRunMockState.runsByWorkspace[workspaceId] ?? [];
    if (status) {
      results = results.filter((run) => run.status === status);
    }

    return HttpResponse.json(paginate(results, url));
  }),

  http.get(`${BASE}/api/v1/workspaces/:workspaceId/agent-runs/:runId/`, async ({ params }) => {
    agentRunMockState.detailCallCount += 1;

    if (agentRunMockState.detailNetworkError) {
      return HttpResponse.error();
    }

    const workspaceId = params.workspaceId as string;
    const runId = params.runId as string;
    const run = (agentRunMockState.runsByWorkspace[workspaceId] ?? []).find(
      (candidate) => candidate.id === runId,
    );
    if (!run) {
      return notFound();
    }
    return HttpResponse.json(run);
  }),

  http.get(
    `${BASE}/api/v1/workspaces/:workspaceId/agent-runs/:runId/steps/`,
    async ({ params }) => {
      const workspaceId = params.workspaceId as string;
      const runId = params.runId as string;
      const run = (agentRunMockState.runsByWorkspace[workspaceId] ?? []).find(
        (candidate) => candidate.id === runId,
      );
      if (!run) {
        return notFound();
      }
      return HttpResponse.json(agentRunMockState.stepsByRun[runId] ?? []);
    },
  ),
];
