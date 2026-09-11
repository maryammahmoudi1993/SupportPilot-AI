"use client";

import { useState } from "react";

import { WEBHOOK_EVENT_TYPES } from "@/features/webhooks/types";
import { webhookEventTypeLabel } from "@/features/webhooks/components/webhook-badges";
import { useCreateWebhookEndpointMutation } from "@/features/webhooks/mutations";
import type { WebhookEndpointCreateResponse, WebhookEventTypeValue } from "@/features/webhooks/types";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/**
 * New-endpoint form (master prompt Part D §14-16). URL/event-type
 * validation is mirrored from `webhooks/serializers.py`/`services.py` only
 * as fast client-side feedback — the backend independently re-validates
 * (structural URL parsing, then a real SSRF/global-routability check,
 * `webhooks/security.py resolve_and_validate`) and is always the actual
 * authority; a client-accepted URL can still be server-rejected.
 */
export function CreateWebhookEndpointForm({
  workspaceId,
  onDone,
  onCancel,
}: {
  workspaceId: string;
  onDone: (endpointId: string) => void;
  onCancel: () => void;
}) {
  const mutation = useCreateWebhookEndpointMutation(workspaceId);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [eventTypes, setEventTypes] = useState<WebhookEventTypeValue[]>([]);
  const [clientError, setClientError] = useState<string | null>(null);
  const [created, setCreated] = useState<WebhookEndpointCreateResponse | null>(null);

  function toggleEventType(eventType: WebhookEventTypeValue) {
    setEventTypes((current) =>
      current.includes(eventType)
        ? current.filter((value) => value !== eventType)
        : [...current, eventType],
    );
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setClientError(null);
    if (!name.trim() || !url.trim()) {
      setClientError("Name and URL are required.");
      return;
    }
    if (eventTypes.length === 0) {
      setClientError("Select at least one event type.");
      return;
    }
    mutation.mutate(
      { name: name.trim(), url: url.trim(), subscribed_event_types: eventTypes },
      { onSuccess: (endpoint) => setCreated(endpoint) },
    );
  }

  if (created) {
    return (
      <div
        className="border-border-subtle flex flex-col gap-3 rounded-lg border p-4"
        role="alert"
        aria-label="Webhook signing secret"
      >
        <p className="text-text-primary text-sm font-medium">
          Endpoint created. Save this signing secret now — it will never be shown again.
        </p>
        <Input readOnly value={created.signing_secret} className="font-mono" onFocus={(event) => event.target.select()} />
        <div>
          <Button onClick={() => onDone(created.id)}>I&rsquo;ve saved this secret</Button>
        </div>
      </div>
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="border-border-subtle flex flex-col gap-4 rounded-lg border p-4"
      aria-label="New webhook endpoint"
    >
      <div>
        <Label htmlFor="new-endpoint-name">Name</Label>
        <Input
          id="new-endpoint-name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          disabled={mutation.isPending}
          maxLength={200}
          required
        />
      </div>
      <div>
        <Label htmlFor="new-endpoint-url">Destination URL</Label>
        <Input
          id="new-endpoint-url"
          type="url"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          disabled={mutation.isPending}
          maxLength={2048}
          placeholder="https://example.com/hooks/supportpilot"
          required
        />
      </div>
      <fieldset disabled={mutation.isPending}>
        <legend className="text-text-primary text-sm font-medium">Subscribed events</legend>
        <div className="mt-2 flex flex-col gap-1.5">
          {WEBHOOK_EVENT_TYPES.map((eventType) => (
            <label key={eventType} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={eventTypes.includes(eventType)}
                onChange={() => toggleEventType(eventType)}
                className="h-4 w-4"
              />
              {webhookEventTypeLabel(eventType)}
            </label>
          ))}
        </div>
      </fieldset>
      {clientError && <Alert variant="danger">{clientError}</Alert>}
      {mutation.isError && (
        <Alert variant="danger" title="This endpoint could not be created">
          {mutation.error.message}
        </Alert>
      )}
      <div className="flex gap-2">
        <Button type="submit" isLoading={mutation.isPending} disabled={mutation.isPending}>
          Create endpoint
        </Button>
        <Button type="button" variant="secondary" onClick={onCancel} disabled={mutation.isPending}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
