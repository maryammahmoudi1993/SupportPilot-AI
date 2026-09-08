import { Button } from "@/components/ui/button";

/**
 * Prev/Next pagination driven by the backend's actual DRF `PageNumberPagination`
 * contract (`count`/`next`/`previous`/`results` — see common/pagination.py):
 * `hasNext`/`hasPrevious` come straight from whether the response carried a
 * `next`/`previous` URL, never inferred from page-size arithmetic the
 * frontend would have to guess at.
 */
export function Pagination({
  page,
  hasNext,
  hasPrevious,
  onNext,
  onPrevious,
  summary,
}: {
  page: number;
  hasNext: boolean;
  hasPrevious: boolean;
  onNext: () => void;
  onPrevious: () => void;
  summary?: string;
}) {
  return (
    <nav
      aria-label="Pagination"
      className="flex flex-wrap items-center justify-between gap-3 border-t px-1 py-3 text-sm border-border-subtle"
    >
      <span className="text-text-secondary" aria-live="polite">
        {summary ?? `Page ${page}`}
      </span>
      <div className="flex items-center gap-2">
        <Button
          variant="secondary"
          size="sm"
          onClick={onPrevious}
          disabled={!hasPrevious}
          aria-label="Previous page"
        >
          Previous
        </Button>
        <Button variant="secondary" size="sm" onClick={onNext} disabled={!hasNext} aria-label="Next page">
          Next
        </Button>
      </div>
    </nav>
  );
}
