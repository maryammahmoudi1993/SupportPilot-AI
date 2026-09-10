/**
 * Webhooks domain types (Phase 22 Chunk 2 — read-only operational
 * visibility). `WebhookEndpoint` and `WebhookDelivery` are the two real,
 * public entities (backend/webhooks/models.py, serialized by
 * backend/webhooks/serializers.py). Individual `DeliveryAttempt` rows are a
 * real backend model but have no public list/detail endpoint at all —
 * `WebhookDeliverySerializer` only ever surfaces the aggregate
 * `attempt_count`/`max_attempts` plus the single latest attempt's
 * `last_http_status` (a `SerializerMethodField` reading
 * `delivery.attempts.order_by("-attempt_number").first()`). No per-attempt
 * timeline is ever fetched or fabricated here (master prompt Part C §10).
 *
 * Neither the outbound request payload nor the remote response body/headers
 * are exposed by any public serializer at all — verified directly against
 * `webhooks/serializers.py WebhookDeliverySerializer`'s exhaustive field
 * list. There is nothing here for a payload-safety concern to apply to
 * beyond the already-safe `last_error_code` string and `last_http_status`
 * integer.
 *
 * Mutation deferral decision (same posture as
 * features/integrations/types.ts's Chunk 1 decision, master prompt's
 * explicit "read/operations visibility" framing for this chunk): endpoint
 * create/update/enable-disable/rotate-secret and delivery redrive are all
 * real, unambiguous backend endpoints, but every one either accepts a raw
 * destination URL/produces a raw signing secret (create, rotate) or is a
 * genuine operational mutation (status, redrive) explicitly deferred to
 * Chunk 3 by the master prompt. None is implemented this chunk.
 */
import type { components } from "@/types/api";

export type WebhookEndpoint = components["schemas"]["WebhookEndpoint"];
export type WebhookEndpointStatusValue = components["schemas"]["WebhookEndpointStatusEnum"];
export type PaginatedWebhookEndpointList = components["schemas"]["PaginatedWebhookEndpointList"];

/**
 * Schema gap (Category B): the generated `WebhookEndpoint.subscribed_event_types`
 * field is typed `unknown` — drf-spectacular has no way to infer an element
 * type for a plain `JSONField(default=list)` model column (verified against
 * `webhooks/models.py WebhookEndpoint.subscribed_event_types`). The real
 * runtime value is always a `string[]` of `WebhookEventTypeEnum` values
 * (server-validated at write time — `webhooks/services.py
 * _validate_event_types`). Narrowed once here, at the one call site that
 * reads it, rather than scattering casts across every component that
 * renders it.
 */
export function subscribedEventTypes(endpoint: WebhookEndpoint): string[] {
  return Array.isArray(endpoint.subscribed_event_types)
    ? (endpoint.subscribed_event_types as unknown[]).filter(
        (value): value is string => typeof value === "string",
      )
    : [];
}

/**
 * Real, server-owned allowlist (backend/webhooks/models.py
 * `WebhookEventType`) — mirrored here (not imported — frontend/backend are
 * separate deployables), same pattern as every other domain's status-label
 * mirror. An event type outside this set (a future addition, or the plain
 * `string` the generated schema types `WebhookDelivery.event_type` and
 * `WebhookEndpoint.subscribed_event_types` as) falls back to its raw value
 * via `EnumBadge`, never a crash.
 */
export type WebhookEventTypeValue =
  | "approval.requested"
  | "approval.approved"
  | "approval.rejected"
  | "approval.expired"
  | "handoff.created";

/** Real, backend-tested pagination only (webhooks/selectors.py `endpoint_list_for_workspace`/`delivery_list_for_workspace` + `common.pagination.StandardResultsSetPagination`) — no filter/search/ordering param exists for either list (no `filter_backends` on either view, verified against webhooks/views.py). */
export interface WebhookEndpointListParams {
  page: number;
}

export const DEFAULT_WEBHOOK_ENDPOINT_LIST_PARAMS: WebhookEndpointListParams = { page: 1 };

export interface WebhookDeliveryListParams {
  page: number;
}

export const DEFAULT_WEBHOOK_DELIVERY_LIST_PARAMS: WebhookDeliveryListParams = { page: 1 };

/**
 * Schema gap (Category B): the generated `WebhookDelivery` type has no
 * status enum at all — `status`/`event_type` are both typed plain `string`
 * (drf-spectacular can't infer a choices enum from a `CharField(source=...)`
 * declared directly on a plain `Serializer`, unlike a `ModelSerializer`
 * field — verified against `webhooks/serializers.py
 * WebhookDeliverySerializer`). The real values are `notifications.models.
 * DeliveryStatus` (mirrored here, not imported, same posture as every other
 * domain).
 */
export type WebhookDeliveryStatusValue =
  | "pending"
  | "claimed"
  | "retry_scheduled"
  | "delivered"
  | "failed"
  | "dead";

/**
 * The backend's real terminal delivery states (`notifications/models.py
 * DELIVERY_TERMINAL_STATUSES`) — `delivered`/`failed`/`dead` never
 * transition again through the normal claim/complete services; `pending`/
 * `retry_scheduled`/`claimed` can still change. Mirrored here for the same
 * reason `isTerminalDocumentStatus` is in features/knowledge/types.ts: this
 * chunk's detail view can label a delivery settled or still moving without
 * inventing a percentage/ETA, and a `next_attempt_at` value only means
 * anything for a non-terminal delivery (see the component's own comment).
 */
const TERMINAL_DELIVERY_STATUSES: ReadonlySet<string> = new Set(["delivered", "failed", "dead"]);

export function isTerminalDeliveryStatus(status: string): boolean {
  return TERMINAL_DELIVERY_STATUSES.has(status);
}

export type PaginatedWebhookDeliveryList = components["schemas"]["PaginatedWebhookDeliveryList"];

/**
 * Schema gap (Category B): the generated `WebhookDelivery.delivered_at`/
 * `failed_at` fields are typed as required, non-null `string` — but the
 * real backend fields (`notifications/models.py Delivery.delivered_at`/
 * `failed_at`) are `DateTimeField(null=True, blank=True)` and the
 * serializer (`webhooks/serializers.py`, plain `DateTimeField(source=...)`
 * with no `allow_null=True`) still serializes a `None` model value as JSON
 * `null` on output regardless (DRF's `allow_null` only governs input
 * validation, never read serialization) — verified directly against
 * `notifications/models.py`. A `pending`/`claimed`/`retry_scheduled`
 * delivery genuinely has `delivered_at: null` and `failed_at: null`. This
 * type explicitly widens both to `string | null` at the one place this
 * domain's components read them.
 */
export type SafeWebhookDelivery = Omit<
  components["schemas"]["WebhookDelivery"],
  "delivered_at" | "failed_at"
> & {
  delivered_at: string | null;
  failed_at: string | null;
};

export function toSafeWebhookDelivery(delivery: components["schemas"]["WebhookDelivery"]) {
  return delivery as unknown as SafeWebhookDelivery;
}

/**
 * The backend's real webhook-management roles (backend/webhooks/
 * permissions.py `CanManageWebhooks.WEBHOOK_MANAGE_ROLES` — support_manager/
 * admin/owner, deliberately broader than Integrations' owner/admin-only:
 * a webhook endpoint carries no third-party provider credential, only this
 * workspace's own outbound signing secret). Mirrored here (not imported),
 * same pattern as `canManageIntegrations`. Chunk 2 has no manage UI yet —
 * exported now so Chunk 3's mutation controls, and this chunk's own tests
 * asserting "no manage control renders," have a single source of truth.
 */
const WEBHOOK_MANAGE_ROLES: ReadonlySet<string> = new Set(["support_manager", "admin", "owner"]);

export function canManageWebhooks(role: string | undefined): boolean {
  return role !== undefined && WEBHOOK_MANAGE_ROLES.has(role);
}
