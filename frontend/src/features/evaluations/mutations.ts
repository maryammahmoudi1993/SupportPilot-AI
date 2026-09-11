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
  createEvaluationCase,
  createEvaluationDataset,
  updateEvaluationCase,
  updateEvaluationDataset,
} from "@/features/evaluations/api";
import { evaluationKeys } from "@/features/evaluations/query-keys";
import type {
  CreateEvaluationCaseInput,
  CreateEvaluationDatasetInput,
  EvaluationCase,
  EvaluationDataset,
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
