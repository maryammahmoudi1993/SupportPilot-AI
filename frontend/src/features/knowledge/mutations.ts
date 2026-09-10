/**
 * Mutation hooks for the knowledge domain (Phase 21 Chunk 2 — upload,
 * ingestion trigger, retry). Same safety posture as
 * features/approvals/queries.ts's `useDecideApprovalMutation`: every
 * mutation here is `retry: 0` (asserted explicitly, not just relied on) —
 * a blind retry could double-submit a document upload, a source creation,
 * or a re-ingestion trigger.
 *
 * Ambiguous upload failure (master prompt Part C §13): the upload endpoint
 * (`KnowledgeDocumentListCreateView.create`) has no idempotency key, client
 * external ID, or dedupe token of any kind — verified directly against
 * `knowledge/serializers.py KnowledgeDocumentUploadSerializer` (`source_id`,
 * `title`, `file`, `metadata` only) and `knowledge/services.py
 * upload_document` (no duplicate-content check; a resubmit always creates a
 * new `KnowledgeDocument` row). So when the transport itself fails —
 * `ApiError.code` of `"network_error"` or `"timeout"`, meaning the request
 * never received an HTTP response at all — this frontend can never tell
 * "never reached the server" from "reached the server, and the document was
 * persisted, but the response was lost in transit." `isAmbiguousUploadError`
 * below is the single place that distinguishes this from a real, confirmed
 * server rejection (validation/permission/conflict — a response the server
 * definitely sent), so the UI can show honest uncertainty and a path to
 * reconcile (refresh the list) instead of either wrongly claiming "upload
 * failed" or silently auto-resubmitting a possibly-already-persisted upload.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  createKnowledgeSource,
  retryKnowledgeDocument,
  uploadKnowledgeDocument,
} from "@/features/knowledge/api";
import { knowledgeKeys } from "@/features/knowledge/query-keys";
import type {
  CreateKnowledgeSourceInput,
  KnowledgeDocument,
  KnowledgeIngestionJob,
  KnowledgeSource,
  UploadKnowledgeDocumentInput,
} from "@/features/knowledge/types";
import type { ApiError } from "@/lib/api/errors";

/** True only for a request that never reached the backend at all — never for a confirmed server response. */
export function isAmbiguousUploadError(error: ApiError): boolean {
  return error.code === "network_error" || error.code === "timeout";
}

export function useUploadKnowledgeDocumentMutation(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation<
    { document: KnowledgeDocument; ingestion_job: KnowledgeIngestionJob },
    ApiError,
    UploadKnowledgeDocumentInput
  >({
    retry: 0,
    mutationFn: (input) => uploadKnowledgeDocument(workspaceId, input),
    onSuccess: ({ document }) => {
      queryClient.setQueryData(knowledgeKeys.documentDetail(workspaceId, document.id), document);
      void queryClient.invalidateQueries({ queryKey: knowledgeKeys.documentLists(workspaceId) });
    },
  });
}

export function useRetryKnowledgeDocumentMutation(workspaceId: string, documentId: string) {
  const queryClient = useQueryClient();
  return useMutation<KnowledgeIngestionJob, ApiError, void>({
    retry: 0,
    mutationFn: () => retryKnowledgeDocument(workspaceId, documentId),
    onSuccess: () => {
      // The retry response is the *ingestion job*, not the document — the
      // document's own now-`queued` status is fetched fresh (server-
      // authoritative, never guessed) rather than hand-assembled here.
      void queryClient.invalidateQueries({
        queryKey: knowledgeKeys.documentDetail(workspaceId, documentId),
      });
      void queryClient.invalidateQueries({ queryKey: knowledgeKeys.documentLists(workspaceId) });
    },
  });
}

export function useCreateKnowledgeSourceMutation(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation<KnowledgeSource, ApiError, CreateKnowledgeSourceInput>({
    retry: 0,
    mutationFn: (input) => createKnowledgeSource(workspaceId, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: knowledgeKeys.sourceLists(workspaceId) });
      void queryClient.invalidateQueries({
        queryKey: knowledgeKeys.sourceFilterOptions(workspaceId),
      });
    },
  });
}
