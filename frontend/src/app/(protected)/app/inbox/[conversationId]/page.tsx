import { ConversationDetailPage } from "@/features/conversations/components/conversation-detail-page";

export default async function Page(props: PageProps<"/app/inbox/[conversationId]">) {
  const { conversationId } = await props.params;
  return <ConversationDetailPage conversationId={conversationId} />;
}
