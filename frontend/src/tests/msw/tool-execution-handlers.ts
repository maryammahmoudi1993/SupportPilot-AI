/**
 * Request-level mocks for the tool-executions domain, mirroring the real
 * backend contract (tools/views.py, tools/selectors.py, tools/serializers.py):
 * workspace-scoped storage, `agent_run_id`/`status` filtering, DRF
 * `PageNumberPagination`'s `{count,next,previous,results}` envelope, and the
 * global (workspace-independent) tool catalog. Same pattern as
 * agent-run-handlers.ts.
 */
import { HttpResponse, http } from "msw";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface ToolExecutionFixture {
  id: string;
  agent_run_id: string;
  tool_definition_id: string;
  tool_key: string;
  status: string;
  idempotency_key: string;
  arguments_redacted: unknown;
  result_redacted: unknown;
  attempt_count: number;
  timeout_seconds: number;
  started_at: string | null;
  completed_at: string | null;
  error_code: string;
  error_message_safe: string;
  duration_ms: number | null;
  created_at: string;
  updated_at: string;
}

export interface ToolDefinitionFixture {
  id: string;
  key: string;
  display_name: string;
  description: string;
  status: string;
  risk_level: string;
  side_effect_type: string;
  default_timeout_seconds: number;
  max_timeout_seconds: number;
  max_retries: number;
  idempotency_mode: string;
}

export function makeToolExecutionFixture(
  overrides: Partial<ToolExecutionFixture> & {
    id: string;
    agent_run_id: string;
    tool_definition_id: string;
    tool_key: string;
  },
): ToolExecutionFixture {
  return {
    status: "succeeded",
    idempotency_key: "",
    arguments_redacted: {},
    result_redacted: {},
    attempt_count: 1,
    timeout_seconds: 5,
    started_at: "2026-01-01T00:00:00Z",
    completed_at: "2026-01-01T00:00:01Z",
    error_code: "",
    error_message_safe: "",
    duration_ms: 120,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:01Z",
    ...overrides,
  };
}

export function makeToolDefinitionFixture(
  overrides: Partial<ToolDefinitionFixture> & { id: string; key: string; display_name: string },
): ToolDefinitionFixture {
  return {
    description: "",
    status: "active",
    risk_level: "read_only",
    side_effect_type: "none",
    default_timeout_seconds: 5,
    max_timeout_seconds: 10,
    max_retries: 0,
    idempotency_mode: "safe",
    ...overrides,
  };
}

export const toolExecutionMockState = {
  executionsByWorkspace: {} as Record<string, ToolExecutionFixture[]>,
  catalogByWorkspace: {} as Record<string, ToolDefinitionFixture[]>,
  listNetworkError: false,
  catalogNetworkError: false,
  listCallCount: 0,
  catalogCallCount: 0,
};

export function seedToolExecutions(workspaceId: string, executions: ToolExecutionFixture[]): void {
  toolExecutionMockState.executionsByWorkspace[workspaceId] = executions;
}

export function seedToolCatalog(workspaceId: string, definitions: ToolDefinitionFixture[]): void {
  toolExecutionMockState.catalogByWorkspace[workspaceId] = definitions;
}

export function resetToolExecutionMockState(): void {
  toolExecutionMockState.executionsByWorkspace = {};
  toolExecutionMockState.catalogByWorkspace = {};
  toolExecutionMockState.listNetworkError = false;
  toolExecutionMockState.catalogNetworkError = false;
  toolExecutionMockState.listCallCount = 0;
  toolExecutionMockState.catalogCallCount = 0;
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

export const toolExecutionHandlers = [
  http.get(
    `${BASE}/api/v1/workspaces/:workspaceId/tools/tool-executions/`,
    async ({ request, params }) => {
      toolExecutionMockState.listCallCount += 1;

      if (toolExecutionMockState.listNetworkError) {
        return HttpResponse.error();
      }

      const workspaceId = params.workspaceId as string;
      const url = new URL(request.url);
      const status = url.searchParams.get("status");
      const agentRunId = url.searchParams.get("agent_run_id");

      let results = toolExecutionMockState.executionsByWorkspace[workspaceId] ?? [];
      if (status) {
        results = results.filter((execution) => execution.status === status);
      }
      if (agentRunId) {
        results = results.filter((execution) => execution.agent_run_id === agentRunId);
      }

      return HttpResponse.json(paginate(results, url));
    },
  ),

  http.get(`${BASE}/api/v1/workspaces/:workspaceId/tools/`, async ({ request, params }) => {
    toolExecutionMockState.catalogCallCount += 1;

    if (toolExecutionMockState.catalogNetworkError) {
      return HttpResponse.error();
    }

    const workspaceId = params.workspaceId as string;
    const url = new URL(request.url);
    const results = toolExecutionMockState.catalogByWorkspace[workspaceId] ?? [];
    return HttpResponse.json(paginate(results, url));
  }),
];
