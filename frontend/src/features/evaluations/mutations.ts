/**
 * Mutation hooks for the evaluations domain (Phase 23 Chunk 2: Dataset/Case
 * create + edit). Same safety posture as features/knowledge/mutations.ts:
 * every mutation is `retry: 0` (asserted explicitly) — a blind retry could
 * double-submit a dataset/case creation. Duplicate-submit-while-pending is
 * blocked at the calling form (checking `mutation.isPending` before
 * `mutate()`), not here — mirrors every other domain's create-form pattern
 * (see features/knowledge/components/knowledge-source-create-form.tsx).
 *
 * No optimistic concurrency: `evaluations/models.py` carries no
 * `updated_at`-based conflict guard, version field, or ETag for
 * dataset/case writes, and `evaluations/services.py`
 * `update_evaluation_dataset`/`update_evaluation_case` unconditionally
 * overwrite whatever fields are sent — verified directly against the
 * service, not assumed. This frontend does not invent an optimistic-
 * concurrency check the backend does not enforce.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  cancelEvaluationRun,
  compareEvaluationRuns,
  createEvaluationCase,
  createEvaluationDataset,
  replayEvaluationResult,
  startEvaluationRun,
  updateEvaluationCase,
  updateEvaluationDataset,
} from "@/features/evaluations/api";
import { evaluationKeys } from "@/features/evaluations/query-keys";
import type {
  CreateEvaluationCaseInput,
  CreateEvaluationDatasetInput,
  EvaluationCase,
  EvaluationDataset,
  EvaluationResult,
  EvaluationRun,
  EvaluationRunCompareInput,
  EvaluationRunCompareResult,
  StartEvaluationRunInput,
  UpdateEvaluationCaseInput,
  UpdateEvaluationDatasetInput,
} from "@/features/evaluations/types";
import type { ApiError } from "@/lib/api/errors";

export function useCreateEvaluationDatasetMutation(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation<EvaluationDataset, ApiError, CreateEvaluationDatasetInput>({
    retry: 0,
    mutationFn: (input) => createEvaluationDataset(workspaceId, input),
    onSuccess: (dataset) => {
      queryClient.setQueryData(evaluationKeys.datasetDetail(workspaceId, dataset.id), dataset);
      void queryClient.invalidateQueries({ queryKey: evaluationKeys.datasetLists(workspaceId) });
    },
  });
}

export function useUpdateEvaluationDatasetMutation(workspaceId: string, datasetId: string) {
  const queryClient = useQueryClient();
  return useMutation<EvaluationDataset, ApiError, UpdateEvaluationDatasetInput>({
    retry: 0,
    mutationFn: (input) => updateEvaluationDataset(workspaceId, datasetId, input),
    onSuccess: (dataset) => {
      queryClient.setQueryData(evaluationKeys.datasetDetail(workspaceId, datasetId), dataset);
      void queryClient.invalidateQueries({ queryKey: evaluationKeys.datasetLists(workspaceId) });
    },
  });
}

export function useCreateEvaluationCaseMutation(workspaceId: string, datasetId: string) {
  const queryClient = useQueryClient();
  return useMutation<EvaluationCase, ApiError, CreateEvaluationCaseInput>({
    retry: 0,
    mutationFn: (input) => createEvaluationCase(workspaceId, datasetId, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: evaluationKeys.cases(workspaceId, datasetId),
      });
    },
  });
}

export function useUpdateEvaluationCaseMutation(
  workspaceId: string,
  datasetId: string,
  caseId: string,
) {
  const queryClient = useQueryClient();
  return useMutation<EvaluationCase, ApiError, UpdateEvaluationCaseInput>({
    retry: 0,
    mutationFn: (input) => updateEvaluationCase(workspaceId, datasetId, caseId, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: evaluationKeys.cases(workspaceId, datasetId),
      });
    },
  });
}

/**
 * Run execution/cancel/replay/compare mutations (Phase 23 Chunk 3). Every
 * mutation is `retry: 0` — same rationale as every other domain: a blind
 * retry on an ambiguous network completion could double-start a run,
 * double-cancel, double-replay, or resubmit a comparison. Duplicate-submit-
 * while-pending is blocked at each calling control by checking
 * `mutation.isPending` before calling `mutate()`, exactly like every other
 * create-form/action-control in this codebase (see
 * `RedriveDeliveryControl`/dataset-case create forms above) — never inside
 * the hook itself, so the pending state stays visible to the caller for
 * button-disabling and confirmation-dialog gating.
 */
export function useStartEvaluationRunMutation(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation<EvaluationRun, ApiError, StartEvaluationRunInput>({
    retry: 0,
    mutationFn: (input) => startEvaluationRun(workspaceId, input),
    onSuccess: (run) => {
      queryClient.setQueryData(evaluationKeys.runDetail(workspaceId, run.id), run);
      void queryClient.invalidateQueries({ queryKey: evaluationKeys.runLists(workspaceId) });
    },
  });
}

export function useCancelEvaluationRunMutation(workspaceId: string, runId: string) {
  const queryClient = useQueryClient();
  return useMutation<EvaluationRun, ApiError, void>({
    retry: 0,
    mutationFn: () => cancelEvaluationRun(workspaceId, runId),
    onSuccess: (run) => {
      queryClient.setQueryData(evaluationKeys.runDetail(workspaceId, runId), run);
      void queryClient.invalidateQueries({ queryKey: evaluationKeys.runLists(workspaceId) });
      void queryClient.invalidateQueries({ queryKey: evaluationKeys.results(workspaceId, runId) });
    },
  });
}

export function useReplayEvaluationResultMutation(workspaceId: string, runId: string) {
  const queryClient = useQueryClient();
  return useMutation<EvaluationResult, ApiError, string>({
    retry: 0,
    mutationFn: (resultId) => replayEvaluationResult(workspaceId, runId, resultId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: evaluationKeys.results(workspaceId, runId) });
    },
  });
}

/**
 * Compare is read-only from the backend's point of view (no persisted state
 * changes other than an audit event) but is still a `POST`, so it goes
 * through `useMutation` (explicit trigger, `retry: 0`, no automatic
 * refetch-on-window-focus a `useQuery` would otherwise apply to a POST-
 * shaped call) rather than being modeled as a query.
 */
export function useCompareEvaluationRunsMutation(workspaceId: string) {
  return useMutation<EvaluationRunCompareResult, ApiError, EvaluationRunCompareInput>({
    retry: 0,
    mutationFn: (input) => compareEvaluationRuns(workspaceId, input),
  });
}
