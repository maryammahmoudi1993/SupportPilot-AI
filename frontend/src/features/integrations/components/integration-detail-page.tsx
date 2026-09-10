"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import {
  IntegrationConnectionStatusBadge,
  IntegrationEnvironmentBadge,
  integrationProviderLabel,
} from "@/features/integrations/components/integration-badges";
import { useIntegrationConnectionDetailQuery } from "@/features/integrations/queries";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { EntityNotFound } from "@/components/support/entity-not-found";
import { ListError } from "@/components/support/list-error";
import { StructuredPayload } from "@/components/support/structured-payload";
import { Timestamp } from "@/components/support/timestamp";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isValidConnectionId(connectionId: string): boolean {
  return UUID_PATTERN.test(connectionId);
}

function ConnectionNotFound() {
  return (
    <EntityNotFound
      title="Integration connection not found"
      description="This integration connection doesn't exist, or isn't available in your active workspace."
      backHref="/app/integrations"
      backLabel="Back to Integrations"
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

function IntegrationConnectionDetailContent({
  workspaceId,
  connectionId,
}: {
  workspaceId: string;
  connectionId: string;
}) {
  const connectionQuery = useIntegrationConnectionDetailQuery(workspaceId, connectionId);

  if (connectionQuery.isPending) {
    return (
      <div
        className="flex flex-col gap-3"
        role="status"
        aria-label="Loading integration connection"
      >
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
        <span className="sr-only">Loading integration connection</span>
      </div>
    );
  }

  if (connectionQuery.isError) {
    // The backend stably codes every real Http404-raised response as
    // `not_found` (workspace membership resolution, then
    // integrations/selectors.py `connection_get_for_workspace_or_404`) —
    // same contract as every other domain (see knowledge-detail-page.tsx).
    // A foreign workspace's connection ID resolves the same way, so this
    // page can never distinguish "doesn't exist" from "belongs to another
    // workspace" — see EntityNotFound's doc comment.
    if (connectionQuery.error.code === "not_found") {
      return <ConnectionNotFound />;
    }
    return (
      <ListError
        message={connectionQuery.error.message}
        onRetry={() => void connectionQuery.refetch()}
        isRetrying={connectionQuery.isFetching}
      />
    );
  }

  const connection = connectionQuery.data;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Link href="/app/integrations" className="text-primary-700 text-sm hover:underline">
          ← Back to Integrations
        </Link>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle>
              {connection.display_name || integrationProviderLabel(connection.provider)}
            </CardTitle>
            <IntegrationConnectionStatusBadge status={connection.status} />
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Provider" value={integrationProviderLabel(connection.provider)} />
            <Field
              label="Environment"
              value={<IntegrationEnvironmentBadge environment={connection.environment} />}
            />
            {/*
              Credential safety (master prompt Part B §9): never the raw
              credential — only the safe, server-derived
              `credentials_configured` boolean plus the opaque
              `credential_version` counter (never a secret value in itself).
            */}
            <Field
              label="Credentials"
              value={connection.credentials_configured ? "Configured" : "Not configured"}
            />
            <Field label="Credential version" value={connection.credential_version} />
            <Field
              label="Capabilities"
              value={
                connection.capabilities.length > 0 ? connection.capabilities.join(", ") : "None"
              }
            />
            <Field
              label="Last checked"
              value={
                connection.last_checked_at ? (
                  <Timestamp value={connection.last_checked_at} />
                ) : (
                  "—"
                )
              }
            />
            <Field
              label="Last success"
              value={
                connection.last_success_at ? (
                  <Timestamp value={connection.last_success_at} />
                ) : (
                  "—"
                )
              }
            />
            <Field label="Created" value={<Timestamp value={connection.created_at} />} />
          </dl>

          {connection.last_error_code && (
            <dl>
              <dt className="text-text-muted text-xs font-medium uppercase">Last error code</dt>
              <dd className="text-danger-700 mt-1 text-sm break-words whitespace-pre-wrap">
                {connection.last_error_code}
              </dd>
            </dl>
          )}

          <div>
            <span className="text-text-muted text-xs font-medium uppercase">Configuration</span>
            <div className="mt-1">
              <StructuredPayload
                value={connection.configuration}
                label="View configuration"
                defaultOpen={false}
              />
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export function IntegrationConnectionDetailPage({ connectionId }: { connectionId: string }) {
  const workspace = useWorkspace();

  if (!isValidConnectionId(connectionId)) {
    return <ConnectionNotFound />;
  }

  if (workspace.status !== "ready" || !workspace.activeWorkspace) {
    return (
      <div className="flex flex-1 items-center justify-center py-16">
        <Spinner label="Loading your workspace" />
      </div>
    );
  }

  return (
    <IntegrationConnectionDetailContent
      workspaceId={workspace.activeWorkspace.id}
      connectionId={connectionId}
    />
  );
}
