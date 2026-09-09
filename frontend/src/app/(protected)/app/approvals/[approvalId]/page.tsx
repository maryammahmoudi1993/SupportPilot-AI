import { ApprovalDetailPage } from "@/features/approvals/components/approval-detail-page";

export default async function Page(props: PageProps<"/app/approvals/[approvalId]">) {
  const { approvalId } = await props.params;
  return <ApprovalDetailPage approvalId={approvalId} />;
}
