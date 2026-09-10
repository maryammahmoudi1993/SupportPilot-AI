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
 * Chunk 1 scope decision (master prompt Part J §35): this chunk implements
 * list + detail only — no create/update/credential-rotate/enable-disable/
 * test-connection mutation. All five exist as real, unambiguous backend
 * endpoints (backend/integrations/urls.py), but every one of them either
 * accepts raw provider credentials directly (create, credential rotate) or
 * is a genuinely separate operational action (enable/disable, test) that
 * deserves its own reviewed UI rather than being bolted onto a foundation
 * chunk. None is "essential to make the Connections UI operational" — a
 * workspace's connections already exist from earlier-phase business
 * integration setup, so a read-only list/detail is a fully real, useful
 * surface on its own. Deferred to a later Phase 22 chunk.
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
