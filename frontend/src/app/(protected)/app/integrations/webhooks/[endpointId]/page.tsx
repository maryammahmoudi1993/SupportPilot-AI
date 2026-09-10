import { WebhookEndpointDetailPage } from "@/features/webhooks/components/webhook-endpoint-detail-page";

export default async function Page(props: PageProps<"/app/integrations/webhooks/[endpointId]">) {
  const { endpointId } = await props.params;
  return <WebhookEndpointDetailPage endpointId={endpointId} />;
}
