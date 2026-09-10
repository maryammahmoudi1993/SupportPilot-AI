"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { KnowledgeDocumentStatusBadge } from "@/features/knowledge/components/knowledge-badges";
import { useRetryKnowledgeDocumentMutation } from "@/features/knowledge/mutations";
import { useKnowledgeDocumentDetailQuery } from "@/features/knowledge/queries";
import {
  canManageKnowledge,
  isRetryableDocumentStatus,
  isTerminalDocumentStatus,
} from "@/features/knowledge/types";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { EntityNotFound } from "@/components/support/entity-not-found";
import { ListError } from "@/components/support/list-error";
import { StructuredPayload } from "@/components/support/structured-payload";
import { Timestamp } from "@/components/support/timestamp";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isValidDocumentId(documentId: string): boolean {
  return UUID_PATTERN.test(documentId);
}

function DocumentNotFound() {
  return (
    <EntityNotFound
      title="Document not found"
      description="This knowledge document doesn't exist, or isn't available in your active workspace."
      backHref="/app/knowledge"
      backLabel="Back to Knowledge"
    />
  );
}

function Field({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-text-muted text-xs font-medium uppercase">{label}</dt>
      <dd className="text-text-primary text-sm">{value}</dd>
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(1)} ${units[unitIndex]}`;
}

function KnowledgeDocumentDetailContent({
  workspaceId,
  documentId,
  canManage,
}: {
  workspaceId: string;
  documentId: string;
  canManage: boolean;
}) {
  const documentQuery = useKnowledgeDocumentDetailQuery(workspaceId, documentId);
  const retryMutation = useRetryKnowledgeDocumentMutation(workspaceId, documentId);

  if (documentQuery.isPending) {
    return (
      <div className="flex flex-col gap-3" role="status" aria-label="Loading knowledge document">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
        <span className="sr-only">Loading knowledge document</span>
      </div>
    );
  }

  if (documentQuery.isError) {
    // The backend stably codes every real Http404-raised response as
    // `not_found` (workspace membership resolution, then
    // knowledge/selectors.py `document_get_for_workspace_or_404`) — same
    // contract as every other domain (see handoff-detail-page.tsx).
    if (documentQuery.error.code === "not_found") {
      return <DocumentNotFound />;
    }
    return (
      <ListError
        message={documentQuery.error.message}
        onRetry={() => void documentQuery.refetch()}
        isRetrying={documentQuery.isFetching}
      />
    );
  }

  const document = documentQuery.data;
  const showRetry = canManage && isRetryableDocumentStatus(document.status);

  function handleRetry() {
    retryMutation.mutate(undefined, {
      onError: () => {
        // A 409 `conflict` here means the real server state has moved on
        // (e.g. already retried/re-processed from another tab) since this
        // page last fetched — refetch and let the actual persisted state
        // redraw the page, same pattern as Approve/Reject
        // (approval-detail-page.tsx).
        void documentQuery.refetch();
      },
    });
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Link href="/app/knowledge" className="text-primary-700 text-sm hover:underline">
          ← Back to Knowledge
        </Link>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle>{document.title}</CardTitle>
            <KnowledgeDocumentStatusBadge status={document.status} />
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field
              label="Source"
              value={
                <Link
                  href={`/app/knowledge?tab=sources&q=${encodeURIComponent(document.source_name)}`}
                  className="text-primary-700 hover:underline focus-visible:underline"
                >
                  {document.source_name}
                </Link>
              }
            />
            <Field label="Original filename" value={document.original_filename} />
            <Field label="File type" value={document.content_type} />
            <Field label="File size" value={formatBytes(document.file_size)} />
            <Field label="Active" value={document.is_active ? "Yes" : "No"} />
            <Field
              label="Processing state"
              value={isTerminalDocumentStatus(document.status) ? "Settled" : "Still in progress"}
            />
            <Field
              label="Extracted characters"
              value={document.extracted_char_count.toLocaleString()}
            />
            <Field label="Chunks" value={document.chunk_count.toLocaleString()} />
            <Field label="Created" value={<Timestamp value={document.created_at} />} />
            <Field
              label="Last ingested"
              value={
                document.last_ingested_at ? <Timestamp value={document.last_ingested_at} /> : "—"
              }
            />
          </dl>

          {document.last_error_code && (
            <dl>
              <dt className="text-text-muted text-xs font-medium uppercase">Last error</dt>
              <dd className="text-danger-700 mt-1 text-sm break-words whitespace-pre-wrap">
                {document.last_error_message_safe || document.last_error_code}
              </dd>
            </dl>
          )}

          {retryMutation.isError && (
            <Alert variant="danger" title="This document could not be queued for retry">
              {retryMutation.error.message}
            </Alert>
          )}

          {showRetry && (
            <div>
              <Button
                variant="secondary"
                size="sm"
                onClick={handleRetry}
                disabled={retryMutation.isPending}
                isLoading={retryMutation.isPending}
              >
                Retry
              </Button>
            </div>
          )}

          <div>
            <span className="text-text-muted text-xs font-medium uppercase">Metadata</span>
            <div className="mt-1">
              <StructuredPayload
                value={document.metadata}
                label="View metadata"
                defaultOpen={false}
              />
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export function KnowledgeDocumentDetailPage({ documentId }: { documentId: string }) {
  const workspace = useWorkspace();

  if (!isValidDocumentId(documentId)) {
    return <DocumentNotFound />;
  }

  if (workspace.status !== "ready" || !workspace.activeWorkspace) {
    return (
      <div className="flex flex-1 items-center justify-center py-16">
        <Spinner label="Loading your workspace" />
      </div>
    );
  }

  return (
    <KnowledgeDocumentDetailContent
      workspaceId={workspace.activeWorkspace.id}
      documentId={documentId}
      canManage={canManageKnowledge(workspace.activeWorkspace.role)}
    />
  );
}
