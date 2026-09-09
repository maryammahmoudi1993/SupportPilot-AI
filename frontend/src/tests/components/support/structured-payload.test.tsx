import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StructuredPayload } from "@/components/support/structured-payload";

describe("StructuredPayload", () => {
  it("renders a dash for null", () => {
    render(<StructuredPayload value={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders a dash for an empty object", () => {
    render(<StructuredPayload value={{}} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders an empty array as real content, not a dash (a real, if empty, list is not the same as no data)", () => {
    render(<StructuredPayload value={[]} />);
    expect(screen.getByText("[]")).toBeInTheDocument();
  });

  it("renders a structured object payload as readable JSON", () => {
    render(<StructuredPayload value={{ order_id: "ord_123", amount: 42 }} />);
    expect(screen.getByText(/"order_id": "ord_123"/)).toBeInTheDocument();
    expect(screen.getByText(/"amount": 42/)).toBeInTheDocument();
  });

  it("renders an array payload", () => {
    render(<StructuredPayload value={["a", "b", "c"]} />);
    expect(screen.getByText(/"a"/)).toBeInTheDocument();
  });

  it("renders primitive values (string, number, boolean) without crashing", () => {
    const { rerender } = render(<StructuredPayload value="a plain string" />);
    expect(screen.getByText('"a plain string"')).toBeInTheDocument();
    rerender(<StructuredPayload value={42} />);
    expect(screen.getByText("42")).toBeInTheDocument();
    rerender(<StructuredPayload value={false} />);
    expect(screen.getByText("false")).toBeInTheDocument();
  });

  it("wraps a long string rather than forcing overflow (whitespace-pre-wrap/break-words applied)", () => {
    const longValue = "x".repeat(500);
    render(<StructuredPayload value={{ note: longValue }} />);
    const pre = document.querySelector("pre");
    expect(pre).not.toBeNull();
    expect(pre?.className).toContain("whitespace-pre-wrap");
    expect(pre?.className).toContain("break-words");
    expect(pre?.className).toContain("overflow-auto");
  });

  it("truncates a pathologically large serialized payload instead of dumping it all unbounded", () => {
    const huge = "y".repeat(30_000);
    render(<StructuredPayload value={{ blob: huge }} />);
    expect(screen.getByText(/truncated/)).toBeInTheDocument();
  });

  it("renders HTML/script-looking text as inert plain text, never interpreted as markup", () => {
    render(
      <StructuredPayload value={{ note: "<b>bold?</b> <script>window.__x = true;</script>" }} />,
    );
    expect(screen.getByText(/<script>/)).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
    expect((window as unknown as { __x?: boolean }).__x).toBeUndefined();
  });

  it("renders a redacted value exactly as the backend sent it (the literal placeholder string), never reconstructing it", () => {
    render(<StructuredPayload value={{ api_key: "***REDACTED***" }} />);
    expect(screen.getByText(/\*\*\*REDACTED\*\*\*/)).toBeInTheDocument();
  });

  it("is a collapsible native disclosure with the given label", () => {
    render(<StructuredPayload value={{ a: 1 }} label="Arguments" />);
    const summary = screen.getByText("Arguments");
    expect(summary.tagName).toBe("SUMMARY");
    expect(summary.closest("details")).not.toBeNull();
  });
});
