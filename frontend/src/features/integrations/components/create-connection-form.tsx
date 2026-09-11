"use client";

import { useState } from "react";

import {
  parseConfigurationInput,
  parseCredentialsInput,
  ProviderConfigurationFields,
  ProviderCredentialsFields,
} from "@/features/integrations/components/provider-fields";
import { useCreateIntegrationConnectionMutation } from "@/features/integrations/mutations";
import type {
  IntegrationEnvironmentValue,
  IntegrationProviderValue,
} from "@/features/integrations/types";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const PROVIDERS: { value: IntegrationProviderValue; label: string }[] = [
  { value: "demo_commerce", label: "Demo commerce (orders & shipments)" },
  { value: "stripe", label: "Stripe" },
  { value: "google_calendar", label: "Google Calendar" },
  { value: "email", label: "Email notifications" },
];

/**
 * New-connection form (Phase 22 Chunk 3, Part C §7-9). `demo_commerce` is
 * listed first deliberately — it is the one provider with no secret
 * material and no real network call (`integrations/providers/
 * demo_commerce.py`), so it is both the safest default selection and the
 * only provider this chunk's real-backend E2E exercises end-to-end.
 *
 * One connection per (workspace, provider) is a real DB constraint
 * (`integrations/models.py uniq_integration_conn_ws_provider`) — a
 * duplicate create surfaces as a normal server validation/conflict error,
 * rendered here exactly as returned, never pre-guessed client-side.
 */
export function CreateConnectionForm({
  workspaceId,
  onCreated,
  onCancel,
}: {
  workspaceId: string;
  onCreated: (connectionId: string) => void;
  onCancel: () => void;
}) {
  const mutation = useCreateIntegrationConnectionMutation(workspaceId);
  const [provider, setProvider] = useState<IntegrationProviderValue>("demo_commerce");
  const [displayName, setDisplayName] = useState("");
  const [environment, setEnvironment] = useState<IntegrationEnvironmentValue>("test");
  const [credentialFields, setCredentialFields] = useState<Record<string, string>>({});
  const [configFields, setConfigFields] = useState<Record<string, string>>({});
  const [clientError, setClientError] = useState<string | null>(null);

  function handleProviderChange(next: IntegrationProviderValue) {
    setProvider(next);
    setCredentialFields({});
    setConfigFields({});
    setClientError(null);
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setClientError(null);

    const credentialsResult = parseCredentialsInput(provider, credentialFields);
    if (!credentialsResult.ok) {
      setClientError(credentialsResult.error);
      return;
    }
    const configurationResult = parseConfigurationInput(provider, configFields);
    if (!configurationResult.ok) {
      setClientError(configurationResult.error);
      return;
    }

    mutation.mutate(
      {
        provider,
        display_name: displayName.trim() || undefined,
        environment,
        credentials: credentialsResult.credentials,
        configuration: configurationResult.configuration,
      },
      {
        onSuccess: (connection) => {
          // Never round-trip submitted secret field state after a
          // confirmed success (master prompt Part C §9).
          setCredentialFields({});
          onCreated(connection.id);
        },
      },
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="border-border-subtle flex flex-col gap-4 rounded-lg border p-4"
      aria-label="New integration connection"
    >
      <div>
        <Label htmlFor="new-connection-provider">Provider</Label>
        <select
          id="new-connection-provider"
          value={provider}
          onChange={(event) => handleProviderChange(event.target.value as IntegrationProviderValue)}
          disabled={mutation.isPending}
          className="bg-surface-0 text-text-primary border-border-default focus-visible:outline-primary-500 h-9 w-full rounded-md border px-3 text-sm outline-none"
        >
          {PROVIDERS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      <div>
        <Label htmlFor="new-connection-display-name">Display name (optional)</Label>
        <Input
          id="new-connection-display-name"
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
          disabled={mutation.isPending}
          maxLength={200}
        />
      </div>

      <div>
        <Label htmlFor="new-connection-environment">Environment</Label>
        <select
          id="new-connection-environment"
          value={environment}
          onChange={(event) => setEnvironment(event.target.value as IntegrationEnvironmentValue)}
          disabled={mutation.isPending}
          className="bg-surface-0 text-text-primary border-border-default focus-visible:outline-primary-500 h-9 w-full rounded-md border px-3 text-sm outline-none"
        >
          <option value="test">Test / sandbox</option>
          <option value="live">Live / production</option>
        </select>
      </div>

      <fieldset className="flex flex-col gap-3" disabled={mutation.isPending}>
        <legend className="text-text-primary text-sm font-medium">Credentials</legend>
        <ProviderCredentialsFields
          provider={provider}
          value={credentialFields}
          onChange={setCredentialFields}
          disabled={mutation.isPending}
          idPrefix="new-connection-cred"
        />
      </fieldset>

      <fieldset className="flex flex-col gap-3" disabled={mutation.isPending}>
        <legend className="text-text-primary text-sm font-medium">Configuration</legend>
        <ProviderConfigurationFields
          provider={provider}
          value={configFields}
          onChange={setConfigFields}
          disabled={mutation.isPending}
          idPrefix="new-connection-config"
        />
      </fieldset>

      {clientError && <Alert variant="danger">{clientError}</Alert>}
      {mutation.isError && (
        <Alert variant="danger" title="This connection could not be created">
          {mutation.error.message}
        </Alert>
      )}

      <div className="flex gap-2">
        <Button type="submit" isLoading={mutation.isPending} disabled={mutation.isPending}>
          Create connection
        </Button>
        <Button
          type="button"
          variant="secondary"
          onClick={onCancel}
          disabled={mutation.isPending}
        >
          Cancel
        </Button>
      </div>
    </form>
  );
}
