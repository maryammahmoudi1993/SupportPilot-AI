import { describe, expect, it } from "vitest";

import { parseWorkspaceMemberships } from "@/features/workspace/parse";

const VALID = { id: "ws-1", name: "Acme Support", slug: "acme-support", role: "support_agent" };

describe("parseWorkspaceMemberships", () => {
  it("accepts a well-formed entry", () => {
    expect(parseWorkspaceMemberships([VALID])).toEqual([VALID]);
  });

  it("passes through multiple well-formed entries in order", () => {
    const second = { ...VALID, id: "ws-2", role: "owner" };
    expect(parseWorkspaceMemberships([VALID, second])).toEqual([VALID, second]);
  });

  it("drops an entry missing id", () => {
    const rest: Record<string, unknown> = { ...VALID };
    delete rest.id;
    expect(parseWorkspaceMemberships([rest])).toEqual([]);
  });

  it("drops an entry with the wrong type for id", () => {
    expect(parseWorkspaceMemberships([{ ...VALID, id: 123 }])).toEqual([]);
  });

  it("drops an entry missing name", () => {
    const rest: Record<string, unknown> = { ...VALID };
    delete rest.name;
    expect(parseWorkspaceMemberships([rest])).toEqual([]);
  });

  it("drops an entry with an unknown role value", () => {
    expect(parseWorkspaceMemberships([{ ...VALID, role: "superadmin" }])).toEqual([]);
  });

  it("drops a null/non-object entry", () => {
    expect(parseWorkspaceMemberships([null, "not-an-object", 42])).toEqual([]);
  });

  it("keeps well-formed entries and drops malformed ones from a mixed array", () => {
    const malformed = { ...VALID, role: "bogus" };
    expect(parseWorkspaceMemberships([VALID, malformed])).toEqual([VALID]);
  });

  it("returns an empty array for an empty input, without throwing", () => {
    expect(parseWorkspaceMemberships([])).toEqual([]);
  });
});
