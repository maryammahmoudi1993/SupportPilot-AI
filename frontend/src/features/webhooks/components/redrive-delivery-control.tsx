"use client";

import { useState } from "react";

import { useRedriveWebhookDeliveryMutation } from "@/features/webhooks/mutations";
import { isRedrivableDeliveryStatus, type SafeWebhookDelivery } from "@/features/webhooks/types";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";

/**
 * Manual redrive control (master prompt Part E §21-25). Only rendered by
 * the caller for a `failed`/`dead` delivery and an authorized role — see
 * `isRedrivableDeliveryStatus`/`canManageWebhooks` in types.ts; the backend
 * (`webhooks/services.py redrive_webhook_delivery`) independently
 * re-validates both the delivery's real current state and the endpoint's
 * real current status regardless of what this control renders.
 *
 * The confirmation copy is deliberately honest about at-least-once
 * semantics (master prompt Part E §22): never "safe retry" / "exactly
 * once" / "will not duplicate" — a redrive really can duplicate whatever
 * external side effect the destination performs on receipt.
 */
export function RedriveDeliveryControl({
  workspaceId,
  delivery,
}: {
  workspaceId: string;
  delivery: SafeWebhookDelivery;
}) {
  const mutation = useRedriveWebhookDeliveryMutation(workspaceId, delivery.delivery_id);
  const [confirmOpen, setConfirmOpen] = useState(false);
  // Recomputed from the live query data on every render (master prompt
  // Part E §24 — server-authoritative): a successful redrive immediately
  // flips this delivery to a non-redrivable status (`pending`), so the
  // button itself must disappear once that happens — but the success
  // message below stays visible (this component instance never unmounts,
  // only its button does) rather than vanishing in the same render as the
  // status change that earned it.
  const isRedrivable = isRedrivableDeliveryStatus(delivery.status);

  if (!isRedrivable && !mutation.isSuccess) {
    return null;
  }

  return (
    <div className="flex flex-col gap-2 border-t pt-4">
      {isRedrivable && (
        <Button
          variant="secondary"
          size="sm"
          onClick={() => setConfirmOpen(true)}
          disabled={mutation.isPending}
          isLoading={mutation.isPending}
        >
          Redrive delivery
        </Button>
      )}
      {mutation.isError && (
        <Alert variant="danger" title="This delivery could not be redriven">
          {mutation.error.message}
        </Alert>
      )}
      {mutation.isSuccess && (
        <Alert variant="success">Delivery queued for another attempt.</Alert>
      )}
      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Redrive this delivery?"
        description="This queues another delivery attempt to the same endpoint. Webhook delivery is at-least-once: if an earlier attempt actually reached the endpoint, redriving may cause it to be processed again."
        confirmLabel="Redrive delivery"
        confirmVariant="primary"
        onConfirm={() => mutation.mutate(undefined, { onSettled: () => setConfirmOpen(false) })}
        isConfirming={mutation.isPending}
      />
    </div>
  );
}
