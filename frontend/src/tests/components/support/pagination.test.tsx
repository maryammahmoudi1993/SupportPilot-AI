import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { Pagination } from "@/components/support/pagination";

/** A minimal, realistic host: page state actually changes on Previous/Next, exactly like every real list page. */
function PaginationHarness({ initialPage = 2 }: { initialPage?: number }) {
  const [page, setPage] = useState(initialPage);
  return (
    <Pagination
      page={page}
      hasPrevious={page > 1}
      hasNext={page < 2}
      onPrevious={() => setPage((p) => Math.max(1, p - 1))}
      onNext={() => setPage((p) => p + 1)}
      summary={`Page ${page}`}
    />
  );
}

describe("Pagination", () => {
  it("recovers focus onto the pagination region when the just-activated button becomes disabled (regression: Phase 19 Chunk 4A keyboard-journey finding)", async () => {
    render(<PaginationHarness initialPage={2} />);
    const user = userEvent.setup();

    const previousButton = screen.getByRole("button", { name: "Previous page" });
    previousButton.focus();
    expect(previousButton).toHaveFocus();

    // Activating it lands on page 1, where Previous becomes disabled —
    // without the fix, focus would be silently lost (stranded) here.
    await user.click(previousButton);

    expect(previousButton).toBeDisabled();
    expect(screen.getByRole("navigation", { name: "Pagination" })).toHaveFocus();
  });

  it("does not steal focus on the very first render, or when focus was never on a pagination button", () => {
    render(<PaginationHarness initialPage={1} />);
    // No prior focus anywhere in this component — its own nav must not
    // grab focus just because it mounted.
    expect(screen.getByRole("navigation", { name: "Pagination" })).not.toHaveFocus();
  });
});
