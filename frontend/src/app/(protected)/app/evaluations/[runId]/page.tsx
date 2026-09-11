import { EvaluationRunDetailPage } from "@/features/evaluations/components/evaluation-run-detail-page";

export default async function Page(props: PageProps<"/app/evaluations/[runId]">) {
  const { runId } = await props.params;
  return <EvaluationRunDetailPage runId={runId} />;
}
