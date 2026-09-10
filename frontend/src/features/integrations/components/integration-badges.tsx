import { EnumBadge } from "@/components/support/enum-badge";
import type {
  IntegrationConnectionStatusValue,
  IntegrationEnvironmentValue,
  IntegrationProviderValue,
} from "@/features/integrations/types";

/** Real values only (backend/integrations/models.py `IntegrationConnectionStatus`) — an unrecognized future status falls back to `EnumBadge`'s neutral variant + the raw value, never a blank/crashed row. */
const STATUS_LABELS: Partial<Record<IntegrationConnectionStatusValue, string>> = {
  active: "Active",
  disabled: "Disabled",
  invalid_credentials: "Invalid credentials",
  degraded: "Degraded",
};

const STATUS_VARIANTS: Partial<
  Record<IntegrationConnectionStatusValue, "success" | "warning" | "danger" | "primary" | "neutral">
> = {
  active: "success",
  disabled: "neutral",
  invalid_credentials: "danger",
  degraded: "warning",
};

export function IntegrationConnectionStatusBadge({
  status,
}: {
  status: IntegrationConnectionStatusValue;
}) {
  return <EnumBadge value={status} labels={STATUS_LABELS} variants={STATUS_VARIANTS} />;
}

/** Real provider catalog only (backend/integrations/models.py `IntegrationProvider` — a server-owned enum, never a client-editable list; see master prompt Part K §36). */
const PROVIDER_LABELS: Partial<Record<IntegrationProviderValue, string>> = {
  stripe: "Stripe",
  google_calendar: "Google Calendar",
  email: "Email notifications",
  demo_commerce: "Demo commerce (orders & shipments)",
};

export function integrationProviderLabel(provider: IntegrationProviderValue): string {
  return PROVIDER_LABELS[provider] ?? provider;
}

const ENVIRONMENT_LABELS: Partial<Record<IntegrationEnvironmentValue, string>> = {
  test: "Test / sandbox",
  live: "Live / production",
};

export function IntegrationEnvironmentBadge({
  environment,
}: {
  environment: IntegrationEnvironmentValue;
}) {
  return (
    <EnumBadge
      value={environment}
      labels={ENVIRONMENT_LABELS}
      variants={{ test: "neutral", live: "primary" }}
    />
  );
}
