import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Alert } from "@/components/ui/alert";

describe("Alert", () => {
  it("uses role=alert for danger so assistive tech announces it immediately", () => {
    render(<Alert variant="danger" title="Something failed" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Something failed");
  });

  it("uses role=status for informational variants", () => {
    render(<Alert variant="info">Heads up.</Alert>);
    expect(screen.getByRole("status")).toHaveTextContent("Heads up.");
  });
});
