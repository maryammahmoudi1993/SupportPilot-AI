import { EnumBadge } from "@/components/support/enum-badge";
import type {
  WebhookDeliveryStatusValue,
  WebhookEndpointStatusValue,
  WebhookEventTypeValue,
} from "@/features/webhooks/types";

const ENDPOINT_STATUS_LABELS: Partial<Record<WebhookEndpointStatusValue, string>> = {
  active: "Active",
  disabled: "Disabled",
};

const ENDPOINT_STATUS_VARIANTS: Partial<
  Record<WebhookEndpointStatusValue, "success" | "warning" | "danger" | "primary" | "neutral">
> = {
  active: "success",
  disabled: "neutral",
};

/** Unknown future status: safe neutral fallback (same pattern as every other domain — see IntegrationConnectionStatusBadge). */
export function WebhookEndpointStatusBadge({ status }: { status: WebhookEndpointStatusValue }) {
  return (
    <EnumBadge value={status} labels={ENDPOINT_STATUS_LABELS} variants={ENDPOINT_STATUS_VARIANTS} />
  );
}

/** Real values only (notifications/models.py `DeliveryStatus`, mirrored — see types.ts's schema-gap note). */
const DELIVERY_STATUS_LABELS: Partial<Record<WebhookDeliveryStatusValue, string>> = {
  pending: "Pending",
  claimed: "In progress",
  retry_scheduled: "Retry scheduled",
  delivered: "Delivered",
  failed: "Failed",
  dead: "Dead",
};

const DELIVERY_STATUS_VARIANTS: Partial<
  Record<WebhookDeliveryStatusValue, "success" | "warning" | "danger" | "primary" | "neutral">
> = {
  pending: "neutral",
  claimed: "warning",
  retry_scheduled: "warning",
  delivered: "success",
  failed: "danger",
  dead: "danger",
};

/** `status` is a real value the generated schema types as plain `string` — an unrecognized value (future backend addition) falls back to `EnumBadge`'s neutral variant + the raw value, never a blank/crashed row. */
export function WebhookDeliveryStatusBadge({ status }: { status: string }) {
  return (
    <EnumBadge
      value={status as WebhookDeliveryStatusValue}
      labels={DELIVERY_STATUS_LABELS}
      variants={DELIVERY_STATUS_VARIANTS}
    />
  );
}

const EVENT_TYPE_LABELS: Partial<Record<WebhookEventTypeValue, string>> = {
  "approval.requested": "Approval requested",
  "approval.approved": "Approval approved",
  "approval.rejected": "Approval rejected",
  "approval.expired": "Approval expired",
  "handoff.created": "Human handoff created",
};

export function webhookEventTypeLabel(eventType: string): string {
  return EVENT_TYPE_LABELS[eventType as WebhookEventTypeValue] ?? eventType;
}
