import { WebhookDeliveryDetailPage } from "@/features/webhooks/components/webhook-delivery-detail-page";

export default async function Page(props: PageProps<"/app/integrations/deliveries/[deliveryId]">) {
  const { deliveryId } = await props.params;
  return <WebhookDeliveryDetailPage deliveryId={deliveryId} />;
}
