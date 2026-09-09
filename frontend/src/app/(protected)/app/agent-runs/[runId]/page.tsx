import { AgentRunDetailPage } from "@/features/agent-runs/components/agent-run-detail-page";

export default async function Page(props: PageProps<"/app/agent-runs/[runId]">) {
  const { runId } = await props.params;
  return <AgentRunDetailPage runId={runId} />;
}
