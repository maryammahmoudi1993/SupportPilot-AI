import { describe, expect, it } from "vitest";

import { customerKeys } from "@/features/customers/query-keys";
import { DEFAULT_CUSTOMER_LIST_PARAMS } from "@/features/customers/types";

describe("customerKeys", () => {
  it("embeds the workspace ID as the second key segment for every key shape", () => {
    expect(customerKeys.all("ws-a")).toEqual(["workspaces", "ws-a", "customers"]);
    expect(customerKeys.lists("ws-a")).toEqual(["workspaces", "ws-a", "customers", "list"]);
    expect(customerKeys.detail("ws-a", "cust-1")).toEqual([
      "workspaces",
      "ws-a",
      "customers",
      "detail",
      "cust-1",
    ]);
  });

  it("produces disjoint list keys for two different workspaces given identical params", () => {
    const keyA = customerKeys.list("ws-a", DEFAULT_CUSTOMER_LIST_PARAMS);
    const keyB = customerKeys.list("ws-b", DEFAULT_CUSTOMER_LIST_PARAMS);
    expect(keyA).not.toEqual(keyB);
    expect(keyA[1]).toBe("ws-a");
    expect(keyB[1]).toBe("ws-b");
  });

  it("produces different list keys when params differ within the same workspace", () => {
    const base = customerKeys.list("ws-a", DEFAULT_CUSTOMER_LIST_PARAMS);
    const filtered = customerKeys.list("ws-a", { ...DEFAULT_CUSTOMER_LIST_PARAMS, search: "jane" });
    expect(base).not.toEqual(filtered);
  });

  it("scopes detail keys under the same workspace-prefixed 'detail' namespace as the list keys' 'list' namespace", () => {
    const detailKey = customerKeys.detail("ws-a", "cust-1");
    const listsKey = customerKeys.lists("ws-a");
    expect(detailKey.slice(0, 2)).toEqual(listsKey.slice(0, 2));
  });
});
