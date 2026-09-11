import { IntegrationConnectionDetailPage } from "@/features/integrations/components/integration-detail-page";

export default async function Page(props: PageProps<"/app/integrations/[connectionId]">) {
  const { connectionId } = await props.params;
  return <IntegrationConnectionDetailPage connectionId={connectionId} />;
}
