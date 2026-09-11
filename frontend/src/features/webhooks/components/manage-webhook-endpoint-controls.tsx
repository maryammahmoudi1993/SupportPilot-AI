"use client";

import { useState } from "react";

import { webhookEventTypeLabel } from "@/features/webhooks/components/webhook-badges";
import {
  useRotateWebhookEndpointSecretMutation,
  useSetWebhookEndpointStatusMutation,
  useUpdateWebhookEndpointMutation,
} from "@/features/webhooks/mutations";
import type { WebhookEndpoint, WebhookEventTypeValue } from "@/features/webhooks/types";
import { WEBHOOK_EVENT_TYPES, subscribedEventTypes } from "@/features/webhooks/types";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** Every real Chunk 3 mutation for one `WebhookEndpoint` detail page: edit (name/URL/events), status enable/disable, and signing-secret rotation. No delete control — `webhooks/urls.py` defines none (master prompt Part D §19). */
export function ManageWebhookEndpointControls({
  workspaceId,
  endpoint,
}: {
  workspaceId: string;
  endpoint: WebhookEndpoint;
}) {
  return (
    <div className="flex flex-col gap-4 border-t pt-4">
      <h2 className="text-text-primary text-sm font-semibold">Manage endpoint</h2>
      <EditEndpointSection workspaceId={workspaceId} endpoint={endpoint} />
      <RotateSecretSection workspaceId={workspaceId} endpoint={endpoint} />
      <StatusSection workspaceId={workspaceId} endpoint={endpoint} />
    </div>
  );
}

function EditEndpointSection({
  workspaceId,
  endpoint,
}: {
  workspaceId: string;
  endpoint: WebhookEndpoint;
}) {
  const mutation = useUpdateWebhookEndpointMutation(workspaceId, endpoint.id);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(endpoint.name);
  const [url, setUrl] = useState(endpoint.url);
  const [eventTypes, setEventTypes] = useState<WebhookEventTypeValue[]>(
    subscribedEventTypes(endpoint) as WebhookEventTypeValue[],
  );
  const [clientError, setClientError] = useState<string | null>(null);

  function toggleEventType(eventType: WebhookEventTypeValue) {
    setEventTypes((current) =>
      current.includes(eventType)
        ? current.filter((value) => value !== eventType)
        : [...current, eventType],
    );
  }

  if (!editing) {
    return (
      <div>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => {
            setName(endpoint.name);
            setUrl(endpoint.url);
            setEventTypes(subscribedEventTypes(endpoint) as WebhookEventTypeValue[]);
            setEditing(true);
          }}
        >
          Edit
        </Button>
      </div>
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
      { onSuccess: () => setEditing(false) },
    );
  }

  return (
    <form onSubmit={handleSubmit} className="border-border-subtle flex flex-col gap-3 rounded-md border p-3">
      <div>
        <Label htmlFor="edit-endpoint-name">Name</Label>
        <Input
          id="edit-endpoint-name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          disabled={mutation.isPending}
          maxLength={200}
        />
      </div>
      <div>
        <Label htmlFor="edit-endpoint-url">Destination URL</Label>
        <Input
          id="edit-endpoint-url"
          type="url"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          disabled={mutation.isPending}
          maxLength={2048}
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
        <Alert variant="danger" title="This endpoint could not be updated">
          {mutation.error.message}
        </Alert>
      )}
      <div className="flex gap-2">
        <Button type="submit" size="sm" isLoading={mutation.isPending} disabled={mutation.isPending}>
          Save changes
        </Button>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={() => setEditing(false)}
          disabled={mutation.isPending}
        >
          Cancel
        </Button>
      </div>
    </form>
  );
}

function RotateSecretSection({
  workspaceId,
  endpoint,
}: {
  workspaceId: string;
  endpoint: WebhookEndpoint;
}) {
  const mutation = useRotateWebhookEndpointSecretMutation(workspaceId, endpoint.id);
  const [confirmOpen, setConfirmOpen] = useState(false);

  if (mutation.isSuccess) {
    return (
      <div
        className="border-border-subtle flex flex-col gap-3 rounded-md border p-3"
        role="alert"
        aria-label="Webhook signing secret"
      >
        <p className="text-text-primary text-sm font-medium">
          Secret rotated. Save it now — it will never be shown again.
        </p>
        <Input
          readOnly
          value={mutation.data.signing_secret}
          className="font-mono"
          onFocus={(event) => event.target.select()}
        />
        <div>
          <Button size="sm" onClick={() => mutation.reset()}>
            I&rsquo;ve saved this secret
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <Button variant="secondary" size="sm" onClick={() => setConfirmOpen(true)}>
        Rotate signing secret
      </Button>
      {mutation.isError && (
        <Alert variant="danger" title="The secret could not be rotated">
          {mutation.error.message}
        </Alert>
      )}
      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Rotate signing secret?"
        description="The previous signing secret stops verifying new deliveries immediately. This action cannot be undone."
        confirmLabel="Rotate secret"
        onConfirm={() => mutation.mutate(undefined, { onSettled: () => setConfirmOpen(false) })}
        isConfirming={mutation.isPending}
      />
    </div>
  );
}

function StatusSection({
  workspaceId,
  endpoint,
}: {
  workspaceId: string;
  endpoint: WebhookEndpoint;
}) {
  const mutation = useSetWebhookEndpointStatusMutation(workspaceId, endpoint.id);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const isActive = endpoint.status === "active";

  return (
    <div className="flex flex-col gap-2">
      {mutation.isError && (
        <Alert variant="danger" title="This change could not be saved">
          {mutation.error.message}
        </Alert>
      )}
      {isActive ? (
        <>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setConfirmOpen(true)}
            disabled={mutation.isPending}
            isLoading={mutation.isPending}
          >
            Disable endpoint
          </Button>
          <ConfirmDialog
            open={confirmOpen}
            onOpenChange={setConfirmOpen}
            title="Disable this endpoint?"
            description="No further deliveries will be attempted to this endpoint, including redrives, until it is re-enabled. This does not cancel or undo any delivery already sent."
            confirmLabel="Disable endpoint"
            onConfirm={() =>
              mutation.mutate("disabled", { onSettled: () => setConfirmOpen(false) })
            }
            isConfirming={mutation.isPending}
          />
        </>
      ) : (
        <Button
          size="sm"
          onClick={() => mutation.mutate("active")}
          disabled={mutation.isPending}
          isLoading={mutation.isPending}
        >
          Enable endpoint
        </Button>
      )}
    </div>
  );
}
