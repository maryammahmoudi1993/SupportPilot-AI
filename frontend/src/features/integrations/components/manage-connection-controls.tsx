"use client";

import { useState } from "react";

import {
  parseConfigurationInput,
  parseCredentialsInput,
  ProviderConfigurationFields,
  ProviderCredentialsFields,
} from "@/features/integrations/components/provider-fields";
import {
  useRotateIntegrationCredentialsMutation,
  useSetIntegrationConnectionEnabledMutation,
  useTestIntegrationConnectionMutation,
  useUpdateIntegrationConnectionMutation,
} from "@/features/integrations/mutations";
import type { IntegrationConnection } from "@/features/integrations/types";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/**
 * Every real Chunk 3 mutation for one `IntegrationConnection` detail page:
 * edit (display name/configuration), credential rotation, enable/disable,
 * and test connection. Gated entirely by the caller on
 * `canManageIntegrations` (master prompt Part G §29) — this component
 * itself assumes the caller already decided to render it; the backend
 * remains the actual authority regardless (a stale/elevated client never
 * grants a denied mutation).
 */
export function ManageConnectionControls({
  workspaceId,
  connection,
}: {
  workspaceId: string;
  connection: IntegrationConnection;
}) {
  return (
    <div className="flex flex-col gap-4 border-t pt-4">
      <h2 className="text-text-primary text-sm font-semibold">Manage connection</h2>
      <EditConnectionSection workspaceId={workspaceId} connection={connection} />
      <RotateCredentialsSection workspaceId={workspaceId} connection={connection} />
      <EnabledSection workspaceId={workspaceId} connection={connection} />
      <TestConnectionSection workspaceId={workspaceId} connection={connection} />
    </div>
  );
}

function EditConnectionSection({
  workspaceId,
  connection,
}: {
  workspaceId: string;
  connection: IntegrationConnection;
}) {
  const mutation = useUpdateIntegrationConnectionMutation(workspaceId, connection.id);
  const [editing, setEditing] = useState(false);
  const [displayName, setDisplayName] = useState(connection.display_name);
  const [configFields, setConfigFields] = useState<Record<string, string>>({});
  const [clientError, setClientError] = useState<string | null>(null);

  if (!editing) {
    return (
      <div>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => {
            setDisplayName(connection.display_name);
            setConfigFields({});
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
    const configurationResult = parseConfigurationInput(connection.provider, configFields);
    if (!configurationResult.ok) {
      setClientError(configurationResult.error);
      return;
    }
    mutation.mutate(
      { display_name: displayName.trim(), configuration: configurationResult.configuration },
      { onSuccess: () => setEditing(false) },
    );
  }

  return (
    <form onSubmit={handleSubmit} className="border-border-subtle flex flex-col gap-3 rounded-md border p-3">
      <div>
        <Label htmlFor="edit-connection-display-name">Display name</Label>
        <Input
          id="edit-connection-display-name"
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
          disabled={mutation.isPending}
          maxLength={200}
        />
      </div>
      <fieldset className="flex flex-col gap-3" disabled={mutation.isPending}>
        <legend className="text-text-primary text-sm font-medium">Configuration</legend>
        <p className="text-text-secondary text-xs">
          Leave fields blank to keep this connection&rsquo;s existing configuration where
          applicable.
        </p>
        <ProviderConfigurationFields
          provider={connection.provider}
          value={configFields}
          onChange={setConfigFields}
          disabled={mutation.isPending}
          idPrefix="edit-connection-config"
        />
      </fieldset>
      {clientError && <Alert variant="danger">{clientError}</Alert>}
      {mutation.isError && (
        <Alert variant="danger" title="This connection could not be updated">
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

function RotateCredentialsSection({
  workspaceId,
  connection,
}: {
  workspaceId: string;
  connection: IntegrationConnection;
}) {
  const mutation = useRotateIntegrationCredentialsMutation(workspaceId, connection.id);
  const [rotating, setRotating] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [credentialFields, setCredentialFields] = useState<Record<string, string>>({});
  const [clientError, setClientError] = useState<string | null>(null);

  if (!rotating) {
    return (
      <div>
        <Button variant="secondary" size="sm" onClick={() => setRotating(true)}>
          Rotate credentials
        </Button>
      </div>
    );
  }

  function handleRequestConfirm(event: React.FormEvent) {
    event.preventDefault();
    setClientError(null);
    const result = parseCredentialsInput(connection.provider, credentialFields);
    if (!result.ok) {
      setClientError(result.error);
      return;
    }
    setConfirmOpen(true);
  }

  function handleConfirm() {
    const result = parseCredentialsInput(connection.provider, credentialFields);
    if (!result.ok) {
      setConfirmOpen(false);
      setClientError(result.error);
      return;
    }
    mutation.mutate(
      { credentials: result.credentials },
      {
        onSuccess: () => {
          // Never retained after a confirmed success (master prompt Part C §9/§11).
          setCredentialFields({});
          setRotating(false);
          setConfirmOpen(false);
        },
        onError: () => setConfirmOpen(false),
      },
    );
  }

  return (
    <form
      onSubmit={handleRequestConfirm}
      className="border-border-subtle flex flex-col gap-3 rounded-md border p-3"
    >
      <p className="text-text-secondary text-xs">
        Replacing credentials immediately invalidates the previous ones. This cannot be undone.
      </p>
      <fieldset className="flex flex-col gap-3" disabled={mutation.isPending}>
        <legend className="text-text-primary text-sm font-medium">New credentials</legend>
        <ProviderCredentialsFields
          provider={connection.provider}
          value={credentialFields}
          onChange={setCredentialFields}
          disabled={mutation.isPending}
          idPrefix="rotate-connection-cred"
        />
      </fieldset>
      {clientError && <Alert variant="danger">{clientError}</Alert>}
      {mutation.isError && (
        <Alert variant="danger" title="Credentials could not be rotated">
          {mutation.error.message}
        </Alert>
      )}
      <div className="flex gap-2">
        <Button type="submit" size="sm" variant="danger" disabled={mutation.isPending}>
          Rotate credentials
        </Button>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={() => {
            setCredentialFields({});
            setRotating(false);
          }}
          disabled={mutation.isPending}
        >
          Cancel
        </Button>
      </div>
      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Rotate credentials?"
        description="The previous credentials will stop working immediately. This action cannot be undone."
        confirmLabel="Rotate credentials"
        onConfirm={handleConfirm}
        isConfirming={mutation.isPending}
      />
    </form>
  );
}

function EnabledSection({
  workspaceId,
  connection,
}: {
  workspaceId: string;
  connection: IntegrationConnection;
}) {
  const mutation = useSetIntegrationConnectionEnabledMutation(workspaceId, connection.id);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const isEnabled = connection.status !== "disabled";

  return (
    <div className="flex flex-col gap-2">
      {mutation.isError && (
        <Alert variant="danger" title="This change could not be saved">
          {mutation.error.message}
        </Alert>
      )}
      {isEnabled ? (
        <>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setConfirmOpen(true)}
            disabled={mutation.isPending}
            isLoading={mutation.isPending}
          >
            Disable connection
          </Button>
          <ConfirmDialog
            open={confirmOpen}
            onOpenChange={setConfirmOpen}
            title="Disable this connection?"
            description="Tools that rely on this provider will stop working for this workspace until it is re-enabled."
            confirmLabel="Disable connection"
            onConfirm={() =>
              mutation.mutate(false, { onSettled: () => setConfirmOpen(false) })
            }
            isConfirming={mutation.isPending}
          />
        </>
      ) : (
        <Button
          size="sm"
          onClick={() => mutation.mutate(true)}
          disabled={mutation.isPending}
          isLoading={mutation.isPending}
        >
          Enable connection
        </Button>
      )}
    </div>
  );
}

function TestConnectionSection({
  workspaceId,
  connection,
}: {
  workspaceId: string;
  connection: IntegrationConnection;
}) {
  const mutation = useTestIntegrationConnectionMutation(workspaceId, connection.id);

  return (
    <div className="flex flex-col gap-2">
      <Button
        variant="secondary"
        size="sm"
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending}
        isLoading={mutation.isPending}
      >
        Test connection
      </Button>
      {mutation.isError && (
        <Alert variant="danger" title="The test could not be run">
          {mutation.error.message}
        </Alert>
      )}
      {mutation.isSuccess && (
        <Alert
          variant={mutation.data.ok ? "success" : "danger"}
          title={mutation.data.ok ? "Connection test succeeded" : "Connection test failed"}
        >
          {mutation.data.error_code ? `Error code: ${mutation.data.error_code}` : "No errors reported."}
        </Alert>
      )}
    </div>
  );
}
