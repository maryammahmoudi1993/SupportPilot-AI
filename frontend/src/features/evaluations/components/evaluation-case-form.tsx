"use client";

import { useState } from "react";
import type { FormEvent } from "react";

import type {
  CreateEvaluationCaseInput,
  EvaluationCase,
  EvaluationCaseStatusValue,
  UpdateEvaluationCaseInput,
} from "@/features/evaluations/types";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const STATUS_OPTIONS: { value: EvaluationCaseStatusValue; label: string }[] = [
  { value: "active", label: "Active" },
  { value: "disabled", label: "Disabled" },
];

const TEXTAREA_CLASS =
  "bg-surface-0 text-text-primary placeholder:text-text-muted w-full rounded-md border px-3 py-2 text-sm transition-colors outline-none border-border-default focus-visible:outline-primary-500 disabled:bg-surface-2 disabled:text-text-disabled disabled:cursor-not-allowed font-mono";

/**
 * `seeded_context`/`expectations` are bounded, strictly-validated Pydantic
 * structures server-side (`evaluations/schemas.py` — `extra="forbid"`
 * everywhere), but there is no stable, fully-typed public field list for
 * every nested shape they can carry (deterministic customer/order/payment/
 * shipment/calendar/knowledge seed rows, tool/approval/outcome-assertion
 * expectations). Rather than build a large bespoke form for a structure this
 * open-ended (master prompt Part F §24: "no heavy editor dependency merely
 * for JSON"), both are edited as controlled JSON textareas: `JSON.parse`
 * validated client-side before submit (a parse failure is a safe, local
 * error — never sent to the server), and the real, safe backend
 * `pydantic.ValidationError` message is surfaced verbatim on a 400 the same
 * way any other field error is. Never `eval`/`new Function` — parsing is the
 * only interpretation this form ever performs, and the parsed value is
 * submitted as plain data, never executed.
 */
function parseJsonField(raw: string, label: string): { value: unknown; error: string | null } {
  const trimmed = raw.trim();
  if (trimmed.length === 0) {
    return { value: {}, error: null };
  }
  try {
    return { value: JSON.parse(trimmed) as unknown, error: null };
  } catch {
    return { value: undefined, error: `${label} must be valid JSON.` };
  }
}

type EvaluationCaseFormProps =
  | {
      mode: "create";
      initial?: undefined;
      isPending: boolean;
      error: string | null;
      onSubmit: (input: CreateEvaluationCaseInput) => void;
      onCancel?: () => void;
    }
  | {
      mode: "edit";
      initial: EvaluationCase;
      isPending: boolean;
      error: string | null;
      onSubmit: (input: UpdateEvaluationCaseInput) => void;
      onCancel?: () => void;
    };

export function EvaluationCaseForm(props: EvaluationCaseFormProps) {
  const { mode, initial, isPending, error, onCancel } = props;
  const [key, setKey] = useState(initial?.key ?? "");
  const [name, setName] = useState(initial?.name ?? "");
  const [status, setStatus] = useState<EvaluationCaseStatusValue>(initial?.status ?? "active");
  const [inputMessage, setInputMessage] = useState(initial?.input_message ?? "");
  const [seededContextRaw, setSeededContextRaw] = useState(
    initial ? JSON.stringify(initial.seeded_context ?? {}, null, 2) : "",
  );
  const [expectationsRaw, setExpectationsRaw] = useState(
    initial ? JSON.stringify(initial.expectations ?? {}, null, 2) : "",
  );
  const [localError, setLocalError] = useState<string | null>(null);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isPending) {
      return;
    }
    if (mode === "create" && (key.trim().length === 0 || name.trim().length === 0)) {
      return;
    }

    const seededContext = parseJsonField(seededContextRaw, "Seeded context");
    if (seededContext.error) {
      setLocalError(seededContext.error);
      return;
    }
    const expectations = parseJsonField(expectationsRaw, "Expectations");
    if (expectations.error) {
      setLocalError(expectations.error);
      return;
    }
    setLocalError(null);

    if (props.mode === "create") {
      props.onSubmit({
        key: key.trim(),
        name: name.trim(),
        status,
        input_message: inputMessage,
        seeded_context: seededContext.value,
        expectations: expectations.value,
      } satisfies CreateEvaluationCaseInput);
    } else {
      props.onSubmit({
        name: name.trim(),
        status,
        input_message: inputMessage,
        seeded_context: seededContext.value,
        expectations: expectations.value,
      } satisfies UpdateEvaluationCaseInput);
    }
  }

  const formLabel = mode === "create" ? "Create a new evaluation case" : "Edit evaluation case";
  const displayedError = localError ?? error;

  return (
    <form
      onSubmit={handleSubmit}
      className="border-border-subtle flex flex-col gap-3 rounded-lg border p-4"
      aria-label={formLabel}
    >
      {mode === "create" ? (
        <div>
          <Label htmlFor="eval-case-key">Key</Label>
          <Input
            id="eval-case-key"
            value={key}
            onChange={(event) => setKey(event.target.value)}
            required
            maxLength={128}
            disabled={isPending}
            aria-describedby="eval-case-key-help"
          />
          <p id="eval-case-key-help" className="text-text-secondary mt-1 text-xs">
            Must be unique within this dataset. Cannot be changed after creation.
          </p>
        </div>
      ) : (
        <div>
          <span className="text-text-muted text-xs font-medium uppercase">Key</span>
          <p className="text-text-primary text-sm">{initial?.key}</p>
          <p className="text-text-secondary mt-1 text-xs">
            The case key cannot be changed after creation.
          </p>
        </div>
      )}

      <div>
        <Label htmlFor="eval-case-name">Name</Label>
        <Input
          id="eval-case-name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          required
          maxLength={200}
          disabled={isPending}
        />
      </div>

      <div>
        <Label htmlFor="eval-case-status">Status</Label>
        <select
          id="eval-case-status"
          value={status}
          onChange={(event) => setStatus(event.target.value as EvaluationCaseStatusValue)}
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

      <div>
        <Label htmlFor="eval-case-input-message">Input message</Label>
        <textarea
          id="eval-case-input-message"
          value={inputMessage}
          onChange={(event) => setInputMessage(event.target.value)}
          required
          maxLength={8000}
          rows={3}
          disabled={isPending}
          className={TEXTAREA_CLASS}
        />
      </div>

      <div>
        <Label htmlFor="eval-case-seeded-context">Seeded context (JSON, optional)</Label>
        <textarea
          id="eval-case-seeded-context"
          value={seededContextRaw}
          onChange={(event) => setSeededContextRaw(event.target.value)}
          rows={5}
          disabled={isPending}
          placeholder="{}"
          className={TEXTAREA_CLASS}
        />
      </div>

      <div>
        <Label htmlFor="eval-case-expectations">Expectations (JSON, optional)</Label>
        <textarea
          id="eval-case-expectations"
          value={expectationsRaw}
          onChange={(event) => setExpectationsRaw(event.target.value)}
          rows={5}
          disabled={isPending}
          placeholder="{}"
          className={TEXTAREA_CLASS}
        />
      </div>

      {displayedError && (
        <Alert
          variant="danger"
          title={mode === "create" ? "This case could not be created" : "This case could not be saved"}
        >
          {displayedError}
        </Alert>
      )}

      <div className="flex gap-2">
        <Button
          type="submit"
          size="sm"
          disabled={isPending || (mode === "create" && (key.trim().length === 0 || name.trim().length === 0))}
          isLoading={isPending}
        >
          {mode === "create" ? "Create case" : "Save changes"}
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
