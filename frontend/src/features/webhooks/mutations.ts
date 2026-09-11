/**
 * Mutation hooks for the webhooks domain (Phase 22 Chunk 3). Same
 * `retry: 0` / scoped-invalidation posture as
 * features/integrations/mutations.ts — see that module's doc comment.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  createWebhookEndpoint,
  redriveWebhookDelivery,
  rotateWebhookEndpointSecret,
  setWebhookEndpointStatus,
  updateWebhookEndpoint,
} from "@/features/webhooks/api";
import { webhookKeys } from "@/features/webhooks/query-keys";
import type {
  CreateWebhookEndpointInput,
  SafeWebhookDelivery,
  UpdateWebhookEndpointInput,
  WebhookEndpoint,
  WebhookEndpointCreateResponse,
  WebhookRotateSecretResponse,
} from "@/features/webhooks/types";
import type { ApiError } from "@/lib/api/errors";

export function useCreateWebhookEndpointMutation(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation<WebhookEndpointCreateResponse, ApiError, CreateWebhookEndpointInput>({
    retry: 0,
    mutationFn: (input) => createWebhookEndpoint(workspaceId, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: webhookKeys.endpointLists(workspaceId) });
    },
  });
}

export function useUpdateWebhookEndpointMutation(workspaceId: string, endpointId: string) {
  const queryClient = useQueryClient();
  return useMutation<WebhookEndpoint, ApiError, UpdateWebhookEndpointInput>({
    retry: 0,
    mutationFn: (input) => updateWebhookEndpoint(workspaceId, endpointId, input),
    onSuccess: (endpoint) => {
      queryClient.setQueryData(webhookKeys.endpointDetail(workspaceId, endpointId), endpoint);
      void queryClient.invalidateQueries({ queryKey: webhookKeys.endpointLists(workspaceId) });
    },
  });
}

export function useSetWebhookEndpointStatusMutation(workspaceId: string, endpointId: string) {
  const queryClient = useQueryClient();
  return useMutation<WebhookEndpoint, ApiError, "active" | "disabled">({
    retry: 0,
    mutationFn: (status) => setWebhookEndpointStatus(workspaceId, endpointId, status),
    onSuccess: (endpoint) => {
      queryClient.setQueryData(webhookKeys.endpointDetail(workspaceId, endpointId), endpoint);
      void queryClient.invalidateQueries({ queryKey: webhookKeys.endpointLists(workspaceId) });
    },
  });
}

export function useRotateWebhookEndpointSecretMutation(workspaceId: string, endpointId: string) {
  const queryClient = useQueryClient();
  return useMutation<WebhookRotateSecretResponse, ApiError, void>({
    retry: 0,
    mutationFn: () => rotateWebhookEndpointSecret(workspaceId, endpointId),
    onSuccess: () => {
      // The response is `{ signing_secret }` only, never the full safe
      // endpoint shape (webhooks/serializers.py
      // `WebhookRotateSecretResponseSerializer`) — refetch the detail so
      // `secret_configured`/`secret_created_at` reflect the real new state.
      void queryClient.invalidateQueries({
        queryKey: webhookKeys.endpointDetail(workspaceId, endpointId),
      });
    },
  });
}

/**
 * Real safety limitation (master prompt Part F §27, documented in
 * frontend/README.md): this mutation is proven against the real backend
 * only for its rejection paths (invalid state, disabled endpoint,
 * permission denial, foreign delivery) — a genuinely *successful* redrive
 * always schedules a real Celery dispatch on commit
 * (`webhooks/services.py redrive_webhook_delivery`'s
 * `transaction.on_commit(partial(dispatch_delivery_for_processing, ...))`),
 * which this repository has no safe, non-internet transport for. The
 * success path below is proven by component tests against a mocked
 * response, not real-backend E2E.
 */
export function useRedriveWebhookDeliveryMutation(workspaceId: string, deliveryId: string) {
  const queryClient = useQueryClient();
  return useMutation<SafeWebhookDelivery, ApiError, void>({
    retry: 0,
    mutationFn: () => redriveWebhookDelivery(workspaceId, deliveryId),
    onSuccess: (delivery) => {
      queryClient.setQueryData(webhookKeys.deliveryDetail(workspaceId, deliveryId), delivery);
      void queryClient.invalidateQueries({ queryKey: webhookKeys.deliveryLists(workspaceId) });
    },
  });
}
