import { describe, expect, it } from "vitest";

import { ticketKeys } from "@/features/tickets/query-keys";
import { DEFAULT_TICKET_LIST_PARAMS } from "@/features/tickets/types";

describe("ticketKeys", () => {
  it("embeds the workspace ID as the second key segment for every key shape", () => {
    expect(ticketKeys.all("ws-a")).toEqual(["workspaces", "ws-a", "tickets"]);
    expect(ticketKeys.detail("ws-a", "tick-1")).toEqual([
      "workspaces",
      "ws-a",
      "tickets",
      "detail",
      "tick-1",
    ]);
  });

  it("produces disjoint list keys for two different workspaces given identical params", () => {
    const keyA = ticketKeys.list("ws-a", DEFAULT_TICKET_LIST_PARAMS);
    const keyB = ticketKeys.list("ws-b", DEFAULT_TICKET_LIST_PARAMS);
    expect(keyA).not.toEqual(keyB);
  });

  it("produces disjoint list keys for two different customer filters in the same workspace", () => {
    const keyA = ticketKeys.list("ws-a", { ...DEFAULT_TICKET_LIST_PARAMS, customerId: "cust-1" });
    const keyB = ticketKeys.list("ws-a", { ...DEFAULT_TICKET_LIST_PARAMS, customerId: "cust-2" });
    expect(keyA).not.toEqual(keyB);
  });

  it("does not duplicate a full customer/conversation entity representation inside a ticket key", () => {
    // Ticket list keys carry only the customer *filter value* (an ID),
    // never a synchronized copy of Customer/Conversation query data — those
    // remain the customers/conversations domains' own cache subtrees.
    const key = ticketKeys.list("ws-a", { ...DEFAULT_TICKET_LIST_PARAMS, customerId: "cust-1" });
    expect(key[0]).toBe("workspaces");
    expect(key).not.toContain("customers");
    expect(key).not.toContain("conversations");
  });
});
