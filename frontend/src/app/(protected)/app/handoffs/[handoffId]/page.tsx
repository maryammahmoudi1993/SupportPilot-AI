import { HandoffDetailPage } from "@/features/handoffs/components/handoff-detail-page";

export default async function Page(props: PageProps<"/app/handoffs/[handoffId]">) {
  const { handoffId } = await props.params;
  return <HandoffDetailPage handoffId={handoffId} />;
}
