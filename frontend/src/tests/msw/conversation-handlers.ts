/**
 * Request-level mocks for the conversations domain, mirroring the real
 * backend contract (conversations/views.py, conversations/selectors.py,
 * conversations/serializers.py): workspace-scoped storage,
 * status/channel/unassigned filtering, DRF `PageNumberPagination`'s
 * `{count,next,previous,results}` envelope, messages scoped by BOTH
 * workspace and conversation (a conversation ID from another workspace
 * 404s the messages endpoint too), and the `{error:{code,message}}`
 * failure envelope.
 */
import { HttpResponse, http } from "msw";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface MembershipSummaryFixture {
  id: string;
  email: string;
  role: string;
}

export interface ConversationFixture {
  id: string;
  customer_id: string;
  channel: string;
  status: string;
  subject: string;
  assigned_to: MembershipSummaryFixture | null;
  external_id: string | null;
  started_at: string;
  last_message_at: string | null;
  closed_at: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface MessageFixture {
  id: string;
  sender_type: string;
  sender: MembershipSummaryFixture | null;
  direction: string;
  body: string;
  external_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export function makeConversationFixture(
  overrides: Partial<ConversationFixture> & { id: string; customer_id: string },
): ConversationFixture {
  return {
    channel: "web",
    status: "open",
    subject: "",
    assigned_to: null,
    external_id: null,
    started_at: "2026-01-01T00:00:00Z",
    last_message_at: null,
    closed_at: null,
    metadata: {},
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export function makeMessageFixture(
  overrides: Partial<MessageFixture> & { id: string; sender_type: string; direction: string; body: string },
): MessageFixture {
  return {
    sender: null,
    external_id: null,
    metadata: {},
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export const conversationMockState = {
  conversationsByWorkspace: {} as Record<string, ConversationFixture[]>,
  messagesByConversation: {} as Record<string, MessageFixture[]>,
  /** Which workspace owns a given conversation ID — for the cross-workspace 404 check. */
  conversationWorkspace: {} as Record<string, string>,
  listNetworkError: false,
  detailNetworkError: false,
  messagesNetworkError: false,
  listCallCount: 0,
};

export function seedConversations(workspaceId: string, conversations: ConversationFixture[]): void {
  conversationMockState.conversationsByWorkspace[workspaceId] = conversations;
  for (const conversation of conversations) {
    conversationMockState.conversationWorkspace[conversation.id] = workspaceId;
  }
}

export function seedMessages(conversationId: string, messages: MessageFixture[]): void {
  conversationMockState.messagesByConversation[conversationId] = messages;
}

export function resetConversationMockState(): void {
  conversationMockState.conversationsByWorkspace = {};
  conversationMockState.messagesByConversation = {};
  conversationMockState.conversationWorkspace = {};
  conversationMockState.listNetworkError = false;
  conversationMockState.detailNetworkError = false;
  conversationMockState.messagesNetworkError = false;
  conversationMockState.listCallCount = 0;
}

function notFound() {
  return HttpResponse.json(
    { error: { code: "not_found", message: "Conversation not found." } },
    { status: 404 },
  );
}

function paginate<T>(items: T[], url: URL) {
  const page = Number(url.searchParams.get("page") ?? "1");
  const pageSize = Number(url.searchParams.get("page_size") ?? "50");
  const count = items.length;
  const start = (page - 1) * pageSize;
  const results = items.slice(start, start + pageSize);
  const hasNext = start + pageSize < count;
  const hasPrevious = page > 1;
  const nextUrl = hasNext ? `${url.origin}${url.pathname}?page=${page + 1}` : null;
  const previousUrl = hasPrevious
    ? `${url.origin}${url.pathname}${page - 1 > 1 ? `?page=${page - 1}` : ""}`
    : null;
  return { count, next: nextUrl, previous: previousUrl, results };
}

export const conversationHandlers = [
  http.get(`${BASE}/api/v1/workspaces/:workspaceId/conversations/`, async ({ request, params }) => {
    conversationMockState.listCallCount += 1;

    if (conversationMockState.listNetworkError) {
      return HttpResponse.error();
    }

    const workspaceId = params.workspaceId as string;
    const url = new URL(request.url);
    const status = url.searchParams.get("status");
    const channel = url.searchParams.get("channel");
    const unassigned = url.searchParams.get("unassigned");

    let results = conversationMockState.conversationsByWorkspace[workspaceId] ?? [];
    if (status) {
      results = results.filter((conversation) => conversation.status === status);
    }
    if (channel) {
      results = results.filter((conversation) => conversation.channel === channel);
    }
    if (unassigned === "true") {
      results = results.filter((conversation) => conversation.assigned_to === null);
    }

    return HttpResponse.json(paginate(results, url));
  }),

  http.get(
    `${BASE}/api/v1/workspaces/:workspaceId/conversations/:conversationId/`,
    async ({ params }) => {
      if (conversationMockState.detailNetworkError) {
        return HttpResponse.error();
      }

      const workspaceId = params.workspaceId as string;
      const conversationId = params.conversationId as string;
      const conversation = (conversationMockState.conversationsByWorkspace[workspaceId] ?? []).find(
        (candidate) => candidate.id === conversationId,
      );
      if (!conversation) {
        return notFound();
      }
      return HttpResponse.json(conversation);
    },
  ),

  http.get(
    `${BASE}/api/v1/workspaces/:workspaceId/conversations/:conversationId/messages/`,
    async ({ request, params }) => {
      if (conversationMockState.messagesNetworkError) {
        return HttpResponse.error();
      }

      const workspaceId = params.workspaceId as string;
      const conversationId = params.conversationId as string;
      // Messages are scoped by BOTH workspace and conversation (see
      // conversations/selectors.py `message_get_for_workspace_or_404`'s
      // doc comment) — a conversation ID from a different workspace must
      // 404 exactly like conversation detail does, not silently return an
      // empty (or another workspace's) message list.
      if (conversationMockState.conversationWorkspace[conversationId] !== workspaceId) {
        return notFound();
      }

      const url = new URL(request.url);
      const messages = conversationMockState.messagesByConversation[conversationId] ?? [];
      return HttpResponse.json(paginate(messages, url));
    },
  ),
];
