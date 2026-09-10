import { EnumBadge } from "@/components/support/enum-badge";
import type {
  KnowledgeDocumentStatusValue,
  KnowledgeSourceTypeValue,
} from "@/features/knowledge/types";

const DOCUMENT_STATUS_LABELS: Partial<Record<KnowledgeDocumentStatusValue, string>> = {
  pending: "Pending",
  queued: "Queued",
  processing: "Processing",
  ready: "Ready",
  failed: "Failed",
};

const DOCUMENT_STATUS_VARIANTS: Partial<
  Record<KnowledgeDocumentStatusValue, "success" | "warning" | "danger" | "primary" | "neutral">
> = {
  pending: "neutral",
  queued: "neutral",
  processing: "warning",
  ready: "success",
  failed: "danger",
};

/** Unknown future status value: safe neutral fallback (master prompt Part A §4 pattern, applied here too). */
export function KnowledgeDocumentStatusBadge({ status }: { status: KnowledgeDocumentStatusValue }) {
  return (
    <EnumBadge value={status} labels={DOCUMENT_STATUS_LABELS} variants={DOCUMENT_STATUS_VARIANTS} />
  );
}

const SOURCE_TYPE_LABELS: Partial<Record<KnowledgeSourceTypeValue, string>> = {
  upload: "Upload",
  manual: "Manual",
};

export function knowledgeSourceTypeLabel(sourceType: KnowledgeSourceTypeValue | undefined): string {
  if (!sourceType) {
    return "—";
  }
  return SOURCE_TYPE_LABELS[sourceType] ?? sourceType;
}
