import { EvaluationDatasetDetailPage } from "@/features/evaluations/components/evaluation-dataset-detail-page";

export default async function Page(props: PageProps<"/app/evaluations/datasets/[datasetId]">) {
  const { datasetId } = await props.params;
  return <EvaluationDatasetDetailPage datasetId={datasetId} />;
}
