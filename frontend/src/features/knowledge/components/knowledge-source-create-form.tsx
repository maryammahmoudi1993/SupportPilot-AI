"use client";

import { useState } from "react";
import type { FormEvent } from "react";

import { useCreateKnowledgeSourceMutation } from "@/features/knowledge/mutations";
import type { KnowledgeSource } from "@/features/knowledge/types";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/**
 * Minimal source creation (master prompt Part I §34) — `name` (required)
 * and `description` (optional) only. No source_type/is_active/metadata
 * fields, no edit, no delete, no bulk administration: this exists solely to
 * unblock document upload in a workspace with no active source yet, not to
 * turn Knowledge Sources into a CMS.
 */
export function KnowledgeSourceCreateForm({
  workspaceId,
  onCreated,
  onCancel,
}: {
  workspaceId: string;
  onCreated?: (source: KnowledgeSource) => void;
  onCancel?: () => void;
}) {
  const mutation = useCreateKnowledgeSourceMutation(workspaceId);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mutation.isPending || name.trim().length === 0) {
      return;
    }
    mutation.mutate(
      { name: name.trim(), description: description.trim() || undefined },
      {
        onSuccess: (source) => {
          setName("");
          setDescription("");
          onCreated?.(source);
        },
      },
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="border-border-subtle flex flex-col gap-3 rounded-lg border p-4"
      aria-label="Create a new knowledge source"
    >
      <div>
        <Label htmlFor="new-source-name">Name</Label>
        <Input
          id="new-source-name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          required
          maxLength={200}
          disabled={mutation.isPending}
        />
      </div>
      <div>
        <Label htmlFor="new-source-description">Description (optional)</Label>
        <Input
          id="new-source-description"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          disabled={mutation.isPending}
        />
      </div>

      {mutation.isError && (
        <Alert variant="danger" title="This source could not be created">
          {mutation.error.message}
        </Alert>
      )}

      <div className="flex gap-2">
        <Button
          type="submit"
          size="sm"
          disabled={mutation.isPending || name.trim().length === 0}
          isLoading={mutation.isPending}
        >
          Create source
        </Button>
        {onCancel && (
          <Button type="button" variant="secondary" size="sm" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}
