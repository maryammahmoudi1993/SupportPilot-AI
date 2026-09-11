"use client";

import { useState } from "react";
import type { FormEvent } from "react";

import type {
  CreateEvaluationDatasetInput,
  EvaluationDataset,
  EvaluationDatasetStatusValue,
  UpdateEvaluationDatasetInput,
} from "@/features/evaluations/types";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const STATUS_OPTIONS: { value: EvaluationDatasetStatusValue; label: string }[] = [
  { value: "draft", label: "Draft" },
  { value: "active", label: "Active" },
  { value: "archived", label: "Archived" },
];

/**
 * Shared create/edit form (master prompt Part D §16-18): create posts a full
 * `CreateEvaluationDatasetInput`; edit posts only the mutable
 * `UpdateEvaluationDatasetInput` fields the backend actually reads
 * (evaluations/services.py `update_evaluation_dataset` — name/description/
 * status only). There is no delete/archive endpoint — setting `status` to
 * "archived" via this same edit form IS the real, only soft-removal path
 * (evaluations/models.py `EvaluationDatasetStatus.ARCHIVED`), never a
 * separate destructive action this chunk invents.
 */
type EvaluationDatasetFormProps =
  | {
      mode: "create";
      initial?: undefined;
      isPending: boolean;
      error: string | null;
      onSubmit: (input: CreateEvaluationDatasetInput) => void;
      onCancel?: () => void;
    }
  | {
      mode: "edit";
      initial: EvaluationDataset;
      isPending: boolean;
      error: string | null;
      onSubmit: (input: UpdateEvaluationDatasetInput) => void;
      onCancel?: () => void;
    };

export function EvaluationDatasetForm({
  mode,
  initial,
  isPending,
  error,
  onSubmit,
  onCancel,
}: EvaluationDatasetFormProps) {
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [status, setStatus] = useState<EvaluationDatasetStatusValue>(initial?.status ?? "draft");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isPending || name.trim().length === 0) {
      return;
    }
    onSubmit({
      name: name.trim(),
      description: description.trim(),
      status,
    });
  }

  const formLabel = mode === "create" ? "Create a new evaluation dataset" : "Edit evaluation dataset";

  return (
    <form
      onSubmit={handleSubmit}
      className="border-border-subtle flex flex-col gap-3 rounded-lg border p-4"
      aria-label={formLabel}
    >
      <div>
        <Label htmlFor="eval-dataset-name">Name</Label>
        <Input
          id="eval-dataset-name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          required
          maxLength={200}
          disabled={isPending}
        />
      </div>
      <div>
        <Label htmlFor="eval-dataset-description">Description (optional)</Label>
        <Input
          id="eval-dataset-description"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          disabled={isPending}
        />
      </div>
      <div>
        <Label htmlFor="eval-dataset-status">Status</Label>
        <select
          id="eval-dataset-status"
          value={status}
          onChange={(event) => setStatus(event.target.value as EvaluationDatasetStatusValue)}
          disabled={isPending}
          className="bg-surface-0 text-text-primary border-border-default focus-visible:outline-primary-500 h-9 w-full rounded-md border px-3 text-sm outline-none"
        >
          {STATUS_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      {error && (
        <Alert
          variant="danger"
          title={mode === "create" ? "This dataset could not be created" : "This dataset could not be saved"}
        >
          {error}
        </Alert>
      )}

      <div className="flex gap-2">
        <Button
          type="submit"
          size="sm"
          disabled={isPending || name.trim().length === 0}
          isLoading={isPending}
        >
          {mode === "create" ? "Create dataset" : "Save changes"}
        </Button>
        {onCancel && (
          <Button type="button" variant="secondary" size="sm" onClick={onCancel} disabled={isPending}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}
