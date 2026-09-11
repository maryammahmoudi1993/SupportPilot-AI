/**
 * Integrations domain types (Phase 22 Chunk 1).
 *
 * `IntegrationConnection` is the one real, public entity in scope for this
 * chunk (backend/integrations/models.py, serialized by
 * backend/integrations/serializers.py `IntegrationConnectionSerializer`).
 * The serializer's field list is exhaustive and secret-free by construction
 * — it never includes `encrypted_credentials`; the only credential signal
 * this chunk ever renders is the boolean `credentials_configured` plus the
 * opaque `credential_version` counter. See api.ts for the exact fields and
 * the create-response schema gap.
 *
 * Chunk 1 scope decision (master prompt Part J §35): Chunk 1 implemented
 * list + detail only. Chunk 3 (this addition) implements the five real
 * mutation endpoints (backend/integrations/urls.py) — create, update
 * (display_name/configuration only), credential rotation, enable/disable,
 * and test connection — see the provider credential/configuration schemas
 * below, mirrored directly from backend/integrations/schemas.py (the real,
 * exact, `pydantic`-enforced per-provider shape — never an invented
 * free-form secret editor, per master prompt Part C §8).
 */
import type { components } from "@/types/api";

export type IntegrationConnection = components["schemas"]["IntegrationConnection"];
export type IntegrationProviderValue = components["schemas"]["IntegrationProviderEnum"];
export type IntegrationEnvironmentValue = components["schemas"]["IntegrationEnvironmentEnum"];
export type IntegrationConnectionStatusValue =
  components["schemas"]["IntegrationConnectionStatusEnum"];
export type PaginatedIntegrationConnectionList =
  components["schemas"]["PaginatedIntegrationConnectionList"];

/** Real, backend-tested pagination only (integrations/selectors.py `connection_list_for_workspace` + `common.pagination.StandardResultsSetPagination`) — no filter/search/ordering param exists for this list (no `filter_backends` on `IntegrationConnectionListCreateView`, verified against integrations/views.py). */
export interface IntegrationConnectionListParams {
  page: number;
}

export const DEFAULT_INTEGRATION_CONNECTION_LIST_PARAMS: IntegrationConnectionListParams = {
  page: 1,
};

/**
 * The backend's real integration-management roles
 * (backend/integrations/permissions.py `CanManageIntegrations.
 * INTEGRATION_MANAGE_ROLES` — owner/admin only, deliberately narrower than
 * knowledge's owner/admin/support_manager). Mirrored here (not imported —
 * frontend/backend are separate deployables), same pattern as
 * `canManageKnowledge`. Chunk 1 has no manage UI yet, but this is exported
 * now so a later chunk's mutation controls have a single source of truth to
 * gate on, and so this chunk's tests can assert "no manage control renders
 * for a read-only role" without inventing a second definition.
 */
const INTEGRATION_MANAGE_ROLES: ReadonlySet<string> = new Set(["owner", "admin"]);

export function canManageIntegrations(role: string | undefined): boolean {
  return role !== undefined && INTEGRATION_MANAGE_ROLES.has(role);
}

// ---------------------------------------------------------------------------
// Mutation contracts (Phase 22 Chunk 3)
// ---------------------------------------------------------------------------

/**
 * `IntegrationConnection.credentials`/`configuration` are typed `unknown` by
 * the generator (Category B schema gap — drf-spectacular cannot infer a
 * shape from the `pydantic` validation `integrations/schemas.py` actually
 * performs server-side). The exact per-provider shapes below are mirrored
 * directly from that module, not guessed:
 *
 * - `stripe`: credentials `{ secret_key: string (8-500 chars) }`; no
 *   configuration fields.
 * - `google_calendar`: credentials `{ service_account_info: object }` — the
 *   real schema is `dict[str, Any]` (a full Google service-account JSON key
 *   file), genuinely unbounded/nested by design, never a flat field set;
 *   configuration `{ calendar_id?: string }` (default `"primary"`).
 * - `email`: credentials `{ host, port?, username, password, use_tls? }`;
 *   configuration `{ from_email: string }`.
 * - `demo_commerce`: no credentials (empty object); configuration
 *   `{ orders?: object, shipments?: object }` — a genuinely free-form demo
 *   catalog (`dict[str, dict[str, Any]]`), the one provider with zero
 *   secret material and no real network call (`integrations/providers/
 *   demo_commerce.py`) — the only provider this chunk's E2E exercises with
 *   a live create/edit/rotate/enable/disable/test-connection flow.
 */
export interface StripeCredentialsInput {
  secret_key: string;
}

export interface GoogleCalendarCredentialsInput {
  service_account_info: Record<string, unknown>;
}

export interface SmtpCredentialsInput {
  host: string;
  port?: number;
  username: string;
  password: string;
  use_tls?: boolean;
}

export interface DemoCommerceCredentialsInput {
  [key: string]: never;
}

export type ProviderCredentialsInput =
  | StripeCredentialsInput
  | GoogleCalendarCredentialsInput
  | SmtpCredentialsInput
  | DemoCommerceCredentialsInput;

export interface GoogleCalendarConfigurationInput {
  calendar_id?: string;
}

export interface EmailConfigurationInput {
  from_email: string;
}

export interface DemoCommerceConfigurationInput {
  orders?: Record<string, unknown>;
  shipments?: Record<string, unknown>;
}

export type ProviderConfigurationInput =
  | Record<string, never>
  | GoogleCalendarConfigurationInput
  | EmailConfigurationInput
  | DemoCommerceConfigurationInput;

export interface CreateIntegrationConnectionInput {
  provider: IntegrationProviderValue;
  display_name?: string;
  environment: IntegrationEnvironmentValue;
  credentials: ProviderCredentialsInput;
  configuration?: ProviderConfigurationInput;
}

export interface UpdateIntegrationConnectionInput {
  display_name?: string;
  configuration?: ProviderConfigurationInput;
}

export interface RotateIntegrationCredentialsInput {
  credentials: ProviderCredentialsInput;
}

export type IntegrationConnectionTestResult =
  components["schemas"]["IntegrationConnectionTestResult"];
