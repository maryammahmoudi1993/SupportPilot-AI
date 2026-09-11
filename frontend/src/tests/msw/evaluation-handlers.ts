/**
 * Request-level mocks for the evaluations domain, mirroring the real backend
 * contract (evaluations/views.py, evaluations/selectors.py,
 * evaluations/serializers.py): workspace-scoped storage, `status` filtering
 * for runs, `passed` filtering for results, DRF `PageNumberPagination`'s
 * `{count,next,previous,results}` envelope, and the `{error:{code,message}}`
 * failure envelope. Same pattern as agent-run-handlers.ts.
 */
import { HttpResponse, http } from "msw";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface EvaluationRunFixture {
  id: string;
  dataset_id: string;
  agent_version_id: string;
  status: string;
  provider_mode: string;
  threshold_config: unknown;
  total_cases: number;
  completed_cases: number;
  passed_cases: number;
  failed_cases: number;
  started_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface EvaluationResultFixture {
  id: string;
  case_key: string;
  status: string;
  agent_run_id: string | null;
  scorer_output: unknown;
  passed: boolean | null;
  failure_code: string;
  failure_message_safe: string;
  latency_ms: number | null;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_cost_usd: string | null;
  replay_of_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export function makeEvaluationRunFixture(
  overrides: Partial<EvaluationRunFixture> & {
    id: string;
    dataset_id: string;
    agent_version_id: string;
  },
): EvaluationRunFixture {
  return {
    status: "succeeded",
    provider_mode: "deterministic",
    threshold_config: {},
    total_cases: 2,
    completed_cases: 2,
    passed_cases: 2,
    failed_cases: 0,
    started_at: "2026-01-01T00:00:00Z",
    completed_at: "2026-01-01T00:00:05Z",
    cancelled_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:05Z",
    ...overrides,
  };
}

export function makeEvaluationResultFixture(
  overrides: Partial<EvaluationResultFixture> & { id: string; case_key: string },
): EvaluationResultFixture {
  return {
    status: "succeeded",
    agent_run_id: null,
    scorer_output: {},
    passed: true,
    failure_code: "",
    failure_message_safe: "",
    latency_ms: 42,
    input_tokens: 10,
    output_tokens: 5,
    total_tokens: 15,
    estimated_cost_usd: null,
    replay_of_id: null,
    started_at: "2026-01-01T00:00:00Z",
    completed_at: "2026-01-01T00:00:01Z",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export interface EvaluationDatasetFixture {
  id: string;
  name: string;
  description: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface EvaluationCaseFixture {
  id: string;
  key: string;
  name: string;
  status: string;
  input_message: string;
  seeded_context: unknown;
  expectations: unknown;
  created_at: string;
  updated_at: string;
}

export function makeEvaluationDatasetFixture(
  overrides: Partial<EvaluationDatasetFixture> & { id: string; name: string },
): EvaluationDatasetFixture {
  return {
    description: "",
    status: "active",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export function makeEvaluationCaseFixture(
  overrides: Partial<EvaluationCaseFixture> & { id: string; key: string; name: string },
): EvaluationCaseFixture {
  return {
    status: "active",
    input_message: "Hello.",
    seeded_context: {},
    expectations: {},
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export const evaluationMockState = {
  runsByWorkspace: {} as Record<string, EvaluationRunFixture[]>,
  /** Which workspace owns a given run ID — for the cross-workspace 404 check. */
  runWorkspace: {} as Record<string, string>,
  resultsByRun: {} as Record<string, EvaluationResultFixture[]>,
  listNetworkError: false,
  detailNetworkError: false,
  resultsNetworkError: false,
  listCallCount: 0,
  detailCallCount: 0,
  resultsCallCount: 0,

  datasetsByWorkspace: {} as Record<string, EvaluationDatasetFixture[]>,
  /** Which workspace owns a given dataset ID — for the cross-workspace 404 check. */
  datasetWorkspace: {} as Record<string, string>,
  casesByDataset: {} as Record<string, EvaluationCaseFixture[]>,
  datasetListNetworkError: false,
  datasetDetailNetworkError: false,
  caseListNetworkError: false,
  /** Returns a 400 on the next dataset/case create call, then clears itself. */
  nextCreateDatasetError: null as { status: number; code: string; message: string } | null,
  nextCreateCaseError: null as { status: number; code: string; message: string } | null,
  datasetListCallCount: 0,
  datasetDetailCallCount: 0,
  caseListCallCount: 0,
  datasetCreateCallCount: 0,
  datasetUpdateCallCount: 0,
  caseCreateCallCount: 0,
  caseUpdateCallCount: 0,
};

export function seedEvaluationRuns(workspaceId: string, runs: EvaluationRunFixture[]): void {
  evaluationMockState.runsByWorkspace[workspaceId] = runs;
  for (const run of runs) {
    evaluationMockState.runWorkspace[run.id] = workspaceId;
  }
}

export function seedEvaluationResults(runId: string, results: EvaluationResultFixture[]): void {
  evaluationMockState.resultsByRun[runId] = results;
}

export function seedEvaluationDatasets(
  workspaceId: string,
  datasets: EvaluationDatasetFixture[],
): void {
  evaluationMockState.datasetsByWorkspace[workspaceId] = datasets;
  for (const dataset of datasets) {
    evaluationMockState.datasetWorkspace[dataset.id] = workspaceId;
  }
}

export function seedEvaluationCases(datasetId: string, cases: EvaluationCaseFixture[]): void {
  evaluationMockState.casesByDataset[datasetId] = cases;
}

export function resetEvaluationMockState(): void {
  evaluationMockState.runsByWorkspace = {};
  evaluationMockState.runWorkspace = {};
  evaluationMockState.resultsByRun = {};
  evaluationMockState.listNetworkError = false;
  evaluationMockState.detailNetworkError = false;
  evaluationMockState.resultsNetworkError = false;
  evaluationMockState.listCallCount = 0;
  evaluationMockState.detailCallCount = 0;
  evaluationMockState.resultsCallCount = 0;

  evaluationMockState.datasetsByWorkspace = {};
  evaluationMockState.datasetWorkspace = {};
  evaluationMockState.casesByDataset = {};
  evaluationMockState.datasetListNetworkError = false;
  evaluationMockState.datasetDetailNetworkError = false;
  evaluationMockState.caseListNetworkError = false;
  evaluationMockState.nextCreateDatasetError = null;
  evaluationMockState.nextCreateCaseError = null;
  evaluationMockState.datasetListCallCount = 0;
  evaluationMockState.datasetDetailCallCount = 0;
  evaluationMockState.caseListCallCount = 0;
  evaluationMockState.datasetCreateCallCount = 0;
  evaluationMockState.datasetUpdateCallCount = 0;
  evaluationMockState.caseCreateCallCount = 0;
  evaluationMockState.caseUpdateCallCount = 0;
}

function notFoundRun() {
  return HttpResponse.json(
    { error: { code: "not_found", message: "Evaluation run not found." } },
    { status: 404 },
  );
}

function notFoundDataset() {
  return HttpResponse.json(
    { error: { code: "not_found", message: "Evaluation dataset not found." } },
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

export const evaluationHandlers = [
  http.get(
    `${BASE}/api/v1/workspaces/:workspaceId/evaluations/runs/`,
    async ({ request, params }) => {
      evaluationMockState.listCallCount += 1;

      if (evaluationMockState.listNetworkError) {
        return HttpResponse.error();
      }

      const workspaceId = params.workspaceId as string;
      const url = new URL(request.url);
      const status = url.searchParams.get("status");

      let results = evaluationMockState.runsByWorkspace[workspaceId] ?? [];
      if (status) {
        results = results.filter((run) => run.status === status);
      }

      return HttpResponse.json(paginate(results, url));
    },
  ),

  http.get(
    `${BASE}/api/v1/workspaces/:workspaceId/evaluations/runs/:runId/`,
    async ({ params }) => {
      evaluationMockState.detailCallCount += 1;

      if (evaluationMockState.detailNetworkError) {
        return HttpResponse.error();
      }

      const workspaceId = params.workspaceId as string;
      const runId = params.runId as string;
      const run = (evaluationMockState.runsByWorkspace[workspaceId] ?? []).find(
        (candidate) => candidate.id === runId,
      );
      if (!run) {
        return notFoundRun();
      }
      return HttpResponse.json(run);
    },
  ),

  http.get(
    `${BASE}/api/v1/workspaces/:workspaceId/evaluations/runs/:runId/results/`,
    async ({ request, params }) => {
      evaluationMockState.resultsCallCount += 1;

      if (evaluationMockState.resultsNetworkError) {
        return HttpResponse.error();
      }

      const workspaceId = params.workspaceId as string;
      const runId = params.runId as string;
      const run = (evaluationMockState.runsByWorkspace[workspaceId] ?? []).find(
        (candidate) => candidate.id === runId,
      );
      if (!run) {
        return notFoundRun();
      }

      const url = new URL(request.url);
      const passedParam = url.searchParams.get("passed");
      let results = evaluationMockState.resultsByRun[runId] ?? [];
      if (passedParam !== null) {
        const passed = passedParam.toLowerCase() === "true";
        results = results.filter((result) => result.passed === passed);
      }

      return HttpResponse.json(paginate(results, url));
    },
  ),

  http.get(
    `${BASE}/api/v1/workspaces/:workspaceId/evaluations/datasets/`,
    async ({ request, params }) => {
      evaluationMockState.datasetListCallCount += 1;

      if (evaluationMockState.datasetListNetworkError) {
        return HttpResponse.error();
      }

      const workspaceId = params.workspaceId as string;
      const url = new URL(request.url);
      const status = url.searchParams.get("status");

      let results = evaluationMockState.datasetsByWorkspace[workspaceId] ?? [];
      if (status) {
        results = results.filter((dataset) => dataset.status === status);
      }

      return HttpResponse.json(paginate(results, url));
    },
  ),

  http.post(
    `${BASE}/api/v1/workspaces/:workspaceId/evaluations/datasets/`,
    async ({ request, params }) => {
      evaluationMockState.datasetCreateCallCount += 1;

      if (evaluationMockState.nextCreateDatasetError) {
        const { status, code, message } = evaluationMockState.nextCreateDatasetError;
        evaluationMockState.nextCreateDatasetError = null;
        return HttpResponse.json({ error: { code, message } }, { status });
      }

      const workspaceId = params.workspaceId as string;
      const body = (await request.json()) as { name: string; description?: string; status?: string };
      const existing = evaluationMockState.datasetsByWorkspace[workspaceId] ?? [];
      if (existing.some((dataset) => dataset.name === body.name)) {
        return HttpResponse.json(
          { error: { code: "invalid", message: "A dataset with this name already exists." } },
          { status: 400 },
        );
      }

      const dataset = makeEvaluationDatasetFixture({
        id: `dataset-${existing.length + 1}-${Date.now()}`,
        name: body.name,
        description: body.description ?? "",
        status: body.status ?? "draft",
      });
      evaluationMockState.datasetsByWorkspace[workspaceId] = [...existing, dataset];
      evaluationMockState.datasetWorkspace[dataset.id] = workspaceId;

      return HttpResponse.json(dataset, { status: 201 });
    },
  ),

  http.get(
    `${BASE}/api/v1/workspaces/:workspaceId/evaluations/datasets/:datasetId/`,
    async ({ params }) => {
      evaluationMockState.datasetDetailCallCount += 1;

      if (evaluationMockState.datasetDetailNetworkError) {
        return HttpResponse.error();
      }

      const workspaceId = params.workspaceId as string;
      const datasetId = params.datasetId as string;
      const dataset = (evaluationMockState.datasetsByWorkspace[workspaceId] ?? []).find(
        (candidate) => candidate.id === datasetId,
      );
      if (!dataset) {
        return notFoundDataset();
      }
      return HttpResponse.json(dataset);
    },
  ),

  http.patch(
    `${BASE}/api/v1/workspaces/:workspaceId/evaluations/datasets/:datasetId/`,
    async ({ request, params }) => {
      evaluationMockState.datasetUpdateCallCount += 1;

      const workspaceId = params.workspaceId as string;
      const datasetId = params.datasetId as string;
      const list = evaluationMockState.datasetsByWorkspace[workspaceId] ?? [];
      const dataset = list.find((candidate) => candidate.id === datasetId);
      if (!dataset) {
        return notFoundDataset();
      }

      const body = (await request.json()) as Partial<EvaluationDatasetFixture>;
      Object.assign(dataset, body);
      return HttpResponse.json(dataset);
    },
  ),

  http.get(
    `${BASE}/api/v1/workspaces/:workspaceId/evaluations/datasets/:datasetId/cases/`,
    async ({ request, params }) => {
      evaluationMockState.caseListCallCount += 1;

      if (evaluationMockState.caseListNetworkError) {
        return HttpResponse.error();
      }

      const workspaceId = params.workspaceId as string;
      const datasetId = params.datasetId as string;
      const dataset = (evaluationMockState.datasetsByWorkspace[workspaceId] ?? []).find(
        (candidate) => candidate.id === datasetId,
      );
      if (!dataset) {
        return notFoundDataset();
      }

      const url = new URL(request.url);
      const status = url.searchParams.get("status");
      let results = evaluationMockState.casesByDataset[datasetId] ?? [];
      if (status) {
        results = results.filter((evaluationCase) => evaluationCase.status === status);
      }

      return HttpResponse.json(paginate(results, url));
    },
  ),

  http.post(
    `${BASE}/api/v1/workspaces/:workspaceId/evaluations/datasets/:datasetId/cases/`,
    async ({ request, params }) => {
      evaluationMockState.caseCreateCallCount += 1;

      if (evaluationMockState.nextCreateCaseError) {
        const { status, code, message } = evaluationMockState.nextCreateCaseError;
        evaluationMockState.nextCreateCaseError = null;
        return HttpResponse.json({ error: { code, message } }, { status });
      }

      const workspaceId = params.workspaceId as string;
      const datasetId = params.datasetId as string;
      const dataset = (evaluationMockState.datasetsByWorkspace[workspaceId] ?? []).find(
        (candidate) => candidate.id === datasetId,
      );
      if (!dataset) {
        return notFoundDataset();
      }

      const body = (await request.json()) as {
        key: string;
        name: string;
        status?: string;
        input_message: string;
        seeded_context?: unknown;
        expectations?: unknown;
      };
      const existing = evaluationMockState.casesByDataset[datasetId] ?? [];
      if (existing.some((evaluationCase) => evaluationCase.key === body.key)) {
        return HttpResponse.json(
          { error: { code: "invalid", message: "A case with this key already exists in this dataset." } },
          { status: 400 },
        );
      }

      const evaluationCase = makeEvaluationCaseFixture({
        id: `case-${existing.length + 1}-${Date.now()}`,
        key: body.key,
        name: body.name,
        status: body.status ?? "active",
        input_message: body.input_message,
        seeded_context: body.seeded_context ?? {},
        expectations: body.expectations ?? {},
      });
      evaluationMockState.casesByDataset[datasetId] = [...existing, evaluationCase];

      return HttpResponse.json(evaluationCase, { status: 201 });
    },
  ),

  http.patch(
    `${BASE}/api/v1/workspaces/:workspaceId/evaluations/datasets/:datasetId/cases/:caseId/`,
    async ({ request, params }) => {
      evaluationMockState.caseUpdateCallCount += 1;

      const datasetId = params.datasetId as string;
      const caseId = params.caseId as string;
      const list = evaluationMockState.casesByDataset[datasetId] ?? [];
      const evaluationCase = list.find((candidate) => candidate.id === caseId);
      if (!evaluationCase) {
        return HttpResponse.json(
          { error: { code: "not_found", message: "Evaluation case not found." } },
          { status: 404 },
        );
      }

      const body = (await request.json()) as Partial<EvaluationCaseFixture>;
      Object.assign(evaluationCase, body);
      return HttpResponse.json(evaluationCase);
    },
  ),
];
