"use client";

import { useEffect, useRef } from "react";

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
  const navRef = useRef<HTMLElement>(null);
  const previousBtnRef = useRef<HTMLButtonElement>(null);
  const nextBtnRef = useRef<HTMLButtonElement>(null);
  const lastFocusedButtonRef = useRef<HTMLButtonElement | null>(null);
  const isFirstRender = useRef(true);

  /**
   * A focused Previous/Next button that becomes `disabled` on the page it
   * just navigated to (e.g. Previous, once back on page 1) is removed from
   * the focus order — the browser's own behavior, not a bug in this
   * component — silently stranding a keyboard-only user's focus (Phase 19
   * Chunk 4A finding). Recover it onto this pagination region itself, which
   * stays present and stable across every page change. Tracked via an
   * explicit "which button last had focus" ref rather than checking
   * `document.activeElement === document.body`: where an unfocused disabled
   * control's focus actually lands is a browser implementation detail, not
   * something to depend on.
   */
  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    if (lastFocusedButtonRef.current?.disabled) {
      navRef.current?.focus();
    }
  }, [page]);

  return (
    <nav
      ref={navRef}
      tabIndex={-1}
      aria-label="Pagination"
      className="focus-visible:outline-primary-500 border-border-subtle flex flex-wrap items-center justify-between gap-3 border-t px-1 py-3 text-sm outline-none focus-visible:outline-2"
    >
      <span className="text-text-secondary" aria-live="polite">
        {summary ?? `Page ${page}`}
      </span>
      <div className="flex items-center gap-2">
        <Button
          ref={previousBtnRef}
          variant="secondary"
          size="sm"
          onClick={onPrevious}
          onFocus={() => {
            lastFocusedButtonRef.current = previousBtnRef.current;
          }}
          disabled={!hasPrevious}
          aria-label="Previous page"
        >
          Previous
        </Button>
        <Button
          ref={nextBtnRef}
          variant="secondary"
          size="sm"
          onClick={onNext}
          onFocus={() => {
            lastFocusedButtonRef.current = nextBtnRef.current;
          }}
          disabled={!hasNext}
          aria-label="Next page"
        >
          Next
        </Button>
      </div>
    </nav>
  );
}
