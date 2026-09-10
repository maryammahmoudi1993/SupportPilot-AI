"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";

import {
  isAmbiguousUploadError,
  useUploadKnowledgeDocumentMutation,
} from "@/features/knowledge/mutations";
import { useKnowledgeSourceFilterOptionsQuery } from "@/features/knowledge/queries";
import { knowledgeKeys } from "@/features/knowledge/query-keys";
import {
  KNOWLEDGE_ACCEPTED_FILE_EXTENSIONS,
  KNOWLEDGE_MAX_UPLOAD_BYTES,
} from "@/features/knowledge/types";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const ACCEPT_ATTRIBUTE = KNOWLEDGE_ACCEPTED_FILE_EXTENSIONS.join(",");

function formatMaxSize(bytes: number): string {
  return `${Math.round(bytes / (1024 * 1024))} MB`;
}

/**
 * Upload a document into an existing, active knowledge source (master
 * prompt Part E). Real fields only — `source_id`, `title`, `file`
 * (knowledge/serializers.py `KnowledgeDocumentUploadSerializer`) —
 * `metadata` is a real optional field too but nothing in this chunk's UI
 * needs to set it, so it's never sent (never invented, never a hidden
 * always-empty control).
 */
export function KnowledgeUploadForm({
  workspaceId,
  onCancel,
}: {
  workspaceId: string;
  onCancel?: () => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const sourcesQuery = useKnowledgeSourceFilterOptionsQuery(workspaceId);
  const mutation = useUploadKnowledgeDocumentMutation(workspaceId);

  const [sourceId, setSourceId] = useState("");
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [sizeError, setSizeError] = useState<string | null>(null);

  // Real, tested filter (knowledge/selectors.py `source_list_for_workspace`
  // `is_active`) — an inactive source is a real, documented 409 `conflict`
  // on upload (knowledge/services.py `upload_document`), so it's never
  // offered as a choice here rather than letting a doomed submit happen.
  const activeSources = sourcesQuery.data?.results.filter((source) => source.is_active) ?? [];

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0] ?? null;
    setFile(selected);
    setSizeError(
      selected && selected.size > KNOWLEDGE_MAX_UPLOAD_BYTES
        ? `This file is larger than the ${formatMaxSize(KNOWLEDGE_MAX_UPLOAD_BYTES)} limit. The server will reject it — choose a smaller file.`
        : null,
    );
    if (selected && title.trim().length === 0) {
      setTitle(selected.name);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mutation.isPending || !file || !sourceId || title.trim().length === 0 || sizeError) {
      return;
    }
    mutation.mutate(
      { sourceId, title: title.trim(), file },
      {
        onSuccess: ({ document }) => {
          router.push(`/app/knowledge/${document.id}`);
        },
      },
    );
  }

  function handleRefreshList() {
    void queryClient.invalidateQueries({ queryKey: knowledgeKeys.documentLists(workspaceId) });
  }

  const ambiguousError = mutation.isError && isAmbiguousUploadError(mutation.error);
  const confirmedServerError = mutation.isError && !ambiguousError;
  const canSubmit =
    !mutation.isPending &&
    file !== null &&
    sourceId !== "" &&
    title.trim().length > 0 &&
    !sizeError;

  // `canSubmit` (not the native HTML `required` attribute) is the actual
  // gate — the Source select and File input below use `aria-required`
  // rather than `required` so a missing field is announced to assistive
  // tech without triggering the browser's native constraint-validation
  // popup/submit-block, whose interaction with a programmatically-set
  // `<input type="file">` FileList is unreliable across environments.
  return (
    <form
      onSubmit={handleSubmit}
      className="border-border-subtle flex flex-col gap-3 rounded-lg border p-4"
      aria-label="Upload a knowledge document"
    >
      <div>
        <Label htmlFor="upload-source">Source</Label>
        {activeSources.length === 0 ? (
          <p className="text-text-secondary mt-1 text-sm">
            No active knowledge sources yet.{" "}
            <Link href="?tab=sources" className="text-primary-700 hover:underline">
              Create one in the Sources tab
            </Link>{" "}
            first.
          </p>
        ) : (
          <select
            id="upload-source"
            value={sourceId}
            onChange={(event) => setSourceId(event.target.value)}
            aria-required="true"
            disabled={mutation.isPending}
            className="bg-surface-0 text-text-primary border-border-default focus-visible:outline-primary-500 h-9 w-full rounded-md border px-3 text-sm outline-none"
          >
            <option value="" disabled>
              Select a source
            </option>
            {activeSources.map((source) => (
              <option key={source.id} value={source.id}>
                {source.name}
              </option>
            ))}
          </select>
        )}
      </div>

      <div>
        <Label htmlFor="upload-title">Title</Label>
        <Input
          id="upload-title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          required
          maxLength={255}
          disabled={mutation.isPending}
        />
      </div>

      <div>
        <Label htmlFor="upload-file">File</Label>
        <input
          id="upload-file"
          type="file"
          accept={ACCEPT_ATTRIBUTE}
          onChange={handleFileChange}
          aria-required="true"
          disabled={mutation.isPending}
          className="text-text-primary file:bg-surface-2 block text-sm file:mr-3 file:rounded-md file:border-0 file:px-3 file:py-1.5 file:text-sm file:font-medium"
        />
        <p className="text-text-muted mt-1 text-xs">
          Accepted: {KNOWLEDGE_ACCEPTED_FILE_EXTENSIONS.join(", ")}. Max{" "}
          {formatMaxSize(KNOWLEDGE_MAX_UPLOAD_BYTES)}. The server validates the actual file content
          — this is a convenience check only.
        </p>
        {sizeError && (
          <p className="text-danger-700 mt-1 text-xs" role="alert">
            {sizeError}
          </p>
        )}
      </div>

      {confirmedServerError && (
        <Alert variant="danger" title="This upload was rejected">
          {mutation.error.message}
        </Alert>
      )}

      {ambiguousError && (
        <Alert variant="warning" title="We couldn't confirm this upload was received">
          <p>
            The connection failed before a response arrived, so we don&rsquo;t know whether the
            document was saved. Refresh the list before trying again — resubmitting now could create
            a duplicate if the first attempt actually succeeded.
          </p>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            className="mt-2"
            onClick={handleRefreshList}
          >
            Refresh list
          </Button>
        </Alert>
      )}

      <div className="flex gap-2">
        <Button type="submit" disabled={!canSubmit} isLoading={mutation.isPending}>
          Upload
        </Button>
        {onCancel && (
          <Button
            type="button"
            variant="secondary"
            onClick={onCancel}
            disabled={mutation.isPending}
          >
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}
