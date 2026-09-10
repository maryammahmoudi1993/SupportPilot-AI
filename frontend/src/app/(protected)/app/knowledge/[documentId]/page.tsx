import { KnowledgeDocumentDetailPage } from "@/features/knowledge/components/knowledge-detail-page";

export default async function Page(props: PageProps<"/app/knowledge/[documentId]">) {
  const { documentId } = await props.params;
  return <KnowledgeDocumentDetailPage documentId={documentId} />;
}
