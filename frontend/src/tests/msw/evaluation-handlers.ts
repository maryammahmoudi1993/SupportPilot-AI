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

/**
 * A deterministic, test-controlled gate: a handler `await`s `promise` before
 * responding, and the test decides exactly when that resolves by calling
 * `release()` — no `setTimeout`/sleep involved. Used to prove workspace
 * A→B mutation isolation (Phase 23 Chunk 2A §10-11): a request is held open
 * across a simulated workspace switch, then deliberately released, so the
 * "late response" is reproduced deterministically rather than raced.
 */
interface Gate {
  promise: Promise<void>;
  release: () => void;
}

function createGate(): Gate {
  let release!: () => void;
  const promise = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { promise, release };
}

export interface AgentDefinitionFixture {
  id: string;
  name: string;
  status: string;
}

export interface AgentVersionFixture {
  id: string;
  version: number;
  status: string;
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

  /** Phase 23 Chunk 3: start/cancel/replay/compare + agent-picker support. */
  agentsByWorkspace: {} as Record<string, AgentDefinitionFixture[]>,
  versionsByAgent: {} as Record<string, AgentVersionFixture[]>,
  runCreateCallCount: 0,
  runCancelCallCount: 0,
  replayCallCount: 0,
  compareCallCount: 0,
  /** Holds the corresponding handler open for this many ms — proves duplicate-submit blocking. */
  runCreateDelayMs: 0,
  cancelDelayMs: 0,
  replayDelayMs: 0,
  /** Returns this error on the next run-create call, then clears itself. */
  nextRunCreateError: null as { status: number; code: string; message: string } | null,
  /** Returns this error on the next cancel call, then clears itself. */
  nextCancelError: null as { status: number; code: string; message: string } | null,
  /** Returns this error on the next replay call, then clears itself. */
  nextReplayError: null as { status: number; code: string; message: string } | null,
  /** Returns this error on the next compare call, then clears itself. */
  nextCompareError: null as { status: number; code: string; message: string } | null,

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

  /** Held open until the test calls the returned `release()` — see `Gate` above. */
  datasetCreateGate: null as Gate | null,
  caseUpdateGate: null as Gate | null,
};

/** Arm the dataset-create handler to hang until the returned function is called. */
export function armDatasetCreateGate(): () => void {
  const gate = createGate();
  evaluationMockState.datasetCreateGate = gate;
  return () => gate.release();
}

/** Arm the case-update handler to hang until the returned function is called. */
export function armCaseUpdateGate(): () => void {
  const gate = createGate();
  evaluationMockState.caseUpdateGate = gate;
  return () => gate.release();
}

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

export function seedAgentDefinitions(workspaceId: string, agents: AgentDefinitionFixture[]): void {
  evaluationMockState.agentsByWorkspace[workspaceId] = agents;
}

export function seedAgentVersions(agentId: string, versions: AgentVersionFixture[]): void {
  evaluationMockState.versionsByAgent[agentId] = versions;
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
  evaluationMockState.datasetCreateGate = null;
  evaluationMockState.caseUpdateGate = null;

  evaluationMockState.agentsByWorkspace = {};
  evaluationMockState.versionsByAgent = {};
  evaluationMockState.runCreateCallCount = 0;
  evaluationMockState.runCancelCallCount = 0;
  evaluationMockState.replayCallCount = 0;
  evaluationMockState.compareCallCount = 0;
  evaluationMockState.runCreateDelayMs = 0;
  evaluationMockState.cancelDelayMs = 0;
  evaluationMockState.replayDelayMs = 0;
  evaluationMockState.nextRunCreateError = null;
  evaluationMockState.nextCancelError = null;
  evaluationMockState.nextReplayError = null;
  evaluationMockState.nextCompareError = null;
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

      if (evaluationMockState.datasetCreateGate) {
        await evaluationMockState.datasetCreateGate.promise;
        evaluationMockState.datasetCreateGate = null;
      }

      if (evaluationMockState.nextCreateDatasetError) {
        const { status, code, message } = evaluationMockState.nextCreateDatasetError;
        evaluationMockState.nextCreateDatasetError = null;
        return HttpResponse.json({ error: { code, message } }, { status });
      }

      const workspaceId = params.workspaceId as string;
      const body = (await request.json()) as {
        name: string;
        description?: string;
        status?: string;
      };
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
          {
            error: {
              code: "invalid",
              message: "A case with this key already exists in this dataset.",
            },
          },
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

      if (evaluationMockState.caseUpdateGate) {
        await evaluationMockState.caseUpdateGate.promise;
        evaluationMockState.caseUpdateGate = null;
      }

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

  /**
   * Start/cancel/replay/compare (Phase 23 Chunk 3) + the minimal agent-picker
   * reads they depend on. Mirrors the real backend's transitions (see
   * evaluations/services.py): cancelling an already-terminal run and
   * replaying a non-terminal result are both real 409s, never silent 200s.
   */
  http.post(
    `${BASE}/api/v1/workspaces/:workspaceId/evaluations/runs/`,
    async ({ request, params }) => {
      evaluationMockState.runCreateCallCount += 1;

      if (evaluationMockState.runCreateDelayMs > 0) {
        await new Promise((resolve) => setTimeout(resolve, evaluationMockState.runCreateDelayMs));
      }

      if (evaluationMockState.nextRunCreateError) {
        const { status, code, message } = evaluationMockState.nextRunCreateError;
        evaluationMockState.nextRunCreateError = null;
        return HttpResponse.json({ error: { code, message } }, { status });
      }

      const workspaceId = params.workspaceId as string;
      const body = (await request.json()) as {
        dataset_id: string;
        agent_version_id: string;
        threshold_config?: unknown;
      };
      const existing = evaluationMockState.runsByWorkspace[workspaceId] ?? [];
      const run = makeEvaluationRunFixture({
        id: `run-${existing.length + 1}-${Date.now()}`,
        dataset_id: body.dataset_id,
        agent_version_id: body.agent_version_id,
        status: "pending",
        threshold_config: body.threshold_config ?? {},
        total_cases: 1,
        completed_cases: 0,
        passed_cases: 0,
        failed_cases: 0,
        started_at: null,
        completed_at: null,
      });
      evaluationMockState.runsByWorkspace[workspaceId] = [...existing, run];
      evaluationMockState.runWorkspace[run.id] = workspaceId;
      evaluationMockState.resultsByRun[run.id] = [];

      return HttpResponse.json(run, { status: 201 });
    },
  ),

  http.post(
    `${BASE}/api/v1/workspaces/:workspaceId/evaluations/runs/:runId/cancel/`,
    async ({ params }) => {
      evaluationMockState.runCancelCallCount += 1;

      const workspaceId = params.workspaceId as string;
      const runId = params.runId as string;
      const run = (evaluationMockState.runsByWorkspace[workspaceId] ?? []).find(
        (candidate) => candidate.id === runId,
      );
      if (!run) {
        return notFoundRun();
      }

      if (evaluationMockState.cancelDelayMs > 0) {
        await new Promise((resolve) => setTimeout(resolve, evaluationMockState.cancelDelayMs));
      }

      if (evaluationMockState.nextCancelError) {
        const { status, code, message } = evaluationMockState.nextCancelError;
        evaluationMockState.nextCancelError = null;
        return HttpResponse.json({ error: { code, message } }, { status });
      }

      const terminal = new Set(["succeeded", "partial", "failed", "cancelled"]);
      if (terminal.has(run.status)) {
        return HttpResponse.json(
          {
            error: {
              code: "evaluation_run_not_cancellable",
              message: "This evaluation run can no longer be cancelled.",
            },
          },
          { status: 409 },
        );
      }

      run.status = "cancelled";
      run.cancelled_at = "2026-01-01T00:00:10Z";
      return HttpResponse.json(run);
    },
  ),

  http.post(
    `${BASE}/api/v1/workspaces/:workspaceId/evaluations/runs/:runId/results/:resultId/replay/`,
    async ({ params }) => {
      evaluationMockState.replayCallCount += 1;

      const workspaceId = params.workspaceId as string;
      const runId = params.runId as string;
      const resultId = params.resultId as string;
      const run = (evaluationMockState.runsByWorkspace[workspaceId] ?? []).find(
        (candidate) => candidate.id === runId,
      );
      if (!run) {
        return notFoundRun();
      }
      const results = evaluationMockState.resultsByRun[runId] ?? [];
      const result = results.find((candidate) => candidate.id === resultId);
      if (!result) {
        return HttpResponse.json(
          { error: { code: "not_found", message: "Evaluation result not found." } },
          { status: 404 },
        );
      }

      if (evaluationMockState.replayDelayMs > 0) {
        await new Promise((resolve) => setTimeout(resolve, evaluationMockState.replayDelayMs));
      }

      if (evaluationMockState.nextReplayError) {
        const { status, code, message } = evaluationMockState.nextReplayError;
        evaluationMockState.nextReplayError = null;
        return HttpResponse.json({ error: { code, message } }, { status });
      }

      const terminal = new Set(["succeeded", "failed", "cancelled"]);
      if (!terminal.has(result.status)) {
        return HttpResponse.json(
          {
            error: {
              code: "evaluation_result_not_replayable",
              message: "This result is not in a state that supports replay.",
            },
          },
          { status: 409 },
        );
      }

      const replay = makeEvaluationResultFixture({
        id: `${result.id}-replay-${results.length + 1}`,
        case_key: result.case_key,
        status: "pending",
        passed: null,
        replay_of_id: result.id,
      });
      evaluationMockState.resultsByRun[runId] = [...results, replay];

      return HttpResponse.json(replay, { status: 201 });
    },
  ),

  http.post(`${BASE}/api/v1/workspaces/:workspaceId/evaluations/compare/`, async ({ request }) => {
    evaluationMockState.compareCallCount += 1;

    if (evaluationMockState.nextCompareError) {
      const { status, code, message } = evaluationMockState.nextCompareError;
      evaluationMockState.nextCompareError = null;
      return HttpResponse.json({ error: { code, message } }, { status });
    }

    const body = (await request.json()) as {
      baseline_run_id: string;
      candidate_run_id: string;
    };

    return HttpResponse.json({
      baseline_run_id: body.baseline_run_id,
      candidate_run_id: body.candidate_run_id,
      case_count: 2,
      baseline_metrics: {
        pass_rate: 0.5,
        forbidden_tool_violations: 0,
        approval_violations: 0,
        handoff_rate: 0,
      },
      candidate_metrics: {
        pass_rate: 1,
        forbidden_tool_violations: 0,
        approval_violations: 0,
        handoff_rate: 0,
      },
      deltas: {
        pass_rate: 0.5,
        forbidden_tool_violations: 0,
        approval_violations: 0,
        handoff_rate: 0,
      },
      thresholds: {},
      regressions: [],
      passed: true,
    });
  }),

  http.get(`${BASE}/api/v1/workspaces/:workspaceId/agents/`, async ({ params, request }) => {
    const workspaceId = params.workspaceId as string;
    const url = new URL(request.url);
    const agents = evaluationMockState.agentsByWorkspace[workspaceId] ?? [];
    return HttpResponse.json(paginate(agents, url));
  }),

  http.get(
    `${BASE}/api/v1/workspaces/:workspaceId/agents/:agentId/versions/`,
    async ({ params, request }) => {
      const agentId = params.agentId as string;
      const url = new URL(request.url);
      const versions = evaluationMockState.versionsByAgent[agentId] ?? [];
      return HttpResponse.json(paginate(versions, url));
    },
  ),
];
