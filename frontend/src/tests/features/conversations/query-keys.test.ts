import { describe, expect, it } from "vitest";

import { conversationKeys } from "@/features/conversations/query-keys";
import { DEFAULT_CONVERSATION_LIST_PARAMS } from "@/features/conversations/types";

describe("conversationKeys", () => {
  it("embeds the workspace ID as the second key segment for every key shape", () => {
    expect(conversationKeys.all("ws-a")).toEqual(["workspaces", "ws-a", "conversations"]);
    expect(conversationKeys.detail("ws-a", "conv-1")).toEqual([
      "workspaces",
      "ws-a",
      "conversations",
      "detail",
      "conv-1",
    ]);
    expect(conversationKeys.messageList("ws-a", "conv-1", { page: 1 })).toEqual([
      "workspaces",
      "ws-a",
      "conversations",
      "detail",
      "conv-1",
      "messages",
      { page: 1 },
    ]);
  });

  it("produces disjoint list keys for two different workspaces given identical params", () => {
    const keyA = conversationKeys.list("ws-a", DEFAULT_CONVERSATION_LIST_PARAMS);
    const keyB = conversationKeys.list("ws-b", DEFAULT_CONVERSATION_LIST_PARAMS);
    expect(keyA).not.toEqual(keyB);
  });

  it("nests a conversation's message keys under that conversation's own detail key", () => {
    const detailKey = conversationKeys.detail("ws-a", "conv-1");
    const messagesKey = conversationKeys.messages("ws-a", "conv-1");
    expect(messagesKey.slice(0, detailKey.length)).toEqual(detailKey);
  });

  it("produces disjoint message keys for two different conversations in the same workspace", () => {
    const keyA = conversationKeys.messageList("ws-a", "conv-1", { page: 1 });
    const keyB = conversationKeys.messageList("ws-a", "conv-2", { page: 1 });
    expect(keyA).not.toEqual(keyB);
  });
});
