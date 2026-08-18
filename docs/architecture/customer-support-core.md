# Customer, Conversation, Message, and Ticket Domains

This document describes the core operational data model introduced in Phase 3:
customers, conversations, messages, and tickets. It builds directly on the
tenancy and RBAC primitives described in
[`authentication-tenancy-rbac.md`](../security/authentication-tenancy-rbac.md)
rather than re-implementing them.

## Domain shape

```text
Customer
    |
    +--> Conversation --> Message (immutable event stream)
    |
    +--> Ticket (conversation optional)
```

A `Customer` always belongs to exactly one `Workspace`. A `Conversation` and a
`Ticket` always belong to a `Customer` in the same workspace. A `Ticket` may
optionally reference the `Conversation` it originated from, but never requires
one — a ticket can be created directly from a phone call, an email outside the
platform, or manual staff entry.

## Customer

- `external_id` is optional and unique per workspace (`workspace, external_id`),
  never globally — the same external identifier may exist in two different
  workspaces without conflict. Enforced by a partial `UniqueConstraint`
  (`external_id IS NOT NULL`).
- Identifying fields are normalized on save (whitespace trimmed, email
  lowercased, blank `external_id` becomes `NULL`), never destructively rewritten.
- `display_name` is derived from name/email/company when not explicitly
  supplied, and preserved verbatim when it is.
- Customers are deactivated (`is_active=False`), never hard-deleted, to
  preserve conversation/ticket history. Deactivation is audited
  (`customer.deactivated`); routine field edits are not.

## Conversation

- `channel` (`web`, `chat`, `email`, `sms`, `api`) is a deliberately
  provider-neutral enum — no `gmail`/`twilio`/`intercom` values. Provider
  specifics belong to a later integrations phase.
- `status` lifecycle: `open <-> pending`, and `open`/`pending -> closed`,
  `closed -> open` (reopen). Transitions are enforced by an explicit table in
  `conversations.services`, not by direct field mutation — an invalid
  transition (e.g. `closed -> pending`) is rejected.
- `closed_at` is set on close and cleared on reopen, always inside the same
  transaction as the status change.
- `assigned_to` references a `WorkspaceMembership`, not a bare `User`, so
  assignment is inherently tenant-scoped. If the membership is later removed,
  the FK is `SET_NULL` rather than leaving a dangling authorization
  assumption.
- **Self-assignment rule**: a support agent may self-assign an *unassigned*
  conversation, but may not assign it to a peer, and may not reassign a
  conversation already assigned to someone else. Only `support_manager` and
  above may assign/reassign freely. This is enforced in
  `conversations.services.assign_conversation`, independent of the view layer.
- **Reopen-on-inbound**: an inbound (customer) message arriving on a closed
  conversation reopens it automatically and clears `closed_at` — this happens
  in the same transaction as message creation, not as a side effect a caller
  must remember to trigger.

## Message

- Immutable historical record: there is no update/delete service or API route
  for an existing message. `sender_type` (`customer`, `human_agent`, `ai_agent`,
  `system`) and `direction` (`inbound`, `outbound`, `internal`) are set once at
  creation.
- The staff-facing API can create only `outbound` (to the customer) and
  `internal` (support-only note) messages, and the sender is always derived
  from the authenticated request's own `WorkspaceMembership` — a client can
  never supply `sender_type` or impersonate another sender.
- `inbound` (customer-authored) and `ai_agent`/`system` messages have a service
  function (`create_inbound_message`) but no route in this phase; they exist so
  future integration/webhook and agent phases do not require a schema
  redesign. There is no public unauthenticated ingestion endpoint yet.
- Creating any message updates `conversation.last_message_at` in the same
  transaction.

## Ticket

- Always belongs to a `Customer`; `conversation` is optional.
- `status` lifecycle: `open`, `in_progress`, `pending`, `resolved`, `closed`,
  with an explicit transition table (e.g. `closed` only reopens to `open`).
  Resolving sets `resolved_at`; any transition away from `resolved` clears it.
- `priority` (`low`, `normal`, `high`, `urgent`, default `normal`) exists for
  later policy/automation phases to act on; no SLA calculation exists yet.
  List ordering places `urgent`/`high` first regardless of alphabetic enum
  order.
- Assignment follows the same membership-based, same-workspace,
  manager-vs-self-assign rules as conversations.
- A support agent may update ticket fields or change ticket status only for a
  ticket currently assigned to them; `support_manager` and above may mutate
  any ticket in the workspace. Ticket creation itself has no assignment
  prerequisite.

## RBAC summary

| Capability | viewer | support_agent | support_manager+ |
|---|---:|---:|---:|
| Read customers/conversations/messages/tickets | Yes | Yes | Yes |
| Create/update customers | No | Yes | Yes |
| Create conversations, send messages | No | Yes | Yes |
| Close/reopen/status-change a conversation or ticket | No | only if assigned to them | Yes, any |
| Self-assign an unassigned conversation/ticket | No | Yes | Yes |
| Assign/reassign to another member | No | No | Yes |
| Create tickets | No | Yes | Yes |
| Update a ticket's fields | No | only if assigned to them | Yes, any |

`owner`/`admin` share `support_manager`'s Phase 3 capabilities plus whatever
Phase 2 workspace administration already grants them.

## Tenant isolation

Every list/detail/action endpoint resolves its workspace and object through a
tenant-scoped selector (`customers.selectors`, `conversations.selectors`,
`tickets.selectors`) before any permission or service logic runs. A
foreign-workspace ID — whether in a URL, a list filter, or a relationship
field in a create/update payload (customer, conversation, assignee membership)
— resolves to `404`, identical to an ID that was never allocated. Services
independently re-validate that every referenced object belongs to the
workspace being operated on, so a cross-tenant relationship cannot be created
even if a caller bypassed the view-level selector.

## Audit coverage

```text
customer.deactivated
conversation.assigned / conversation.reassigned
conversation.closed / conversation.reopened
ticket.assigned / ticket.reassigned
ticket.status_changed / ticket.resolved / ticket.reopened
```

Audit metadata is restricted to IDs and structured facts (old/new status,
assignee membership ID) — never message bodies, customer PII, or other
sensitive payload content.

## Known limitations / deferred items

- No external channel ingestion (email/SMS/chat webhooks) — the `channel`,
  `external_id`, and `metadata` fields exist to make that possible later
  without a schema redesign.
- No AI agent behavior, tool calling, retrieval, or policy evaluation — those
  are later phases; the `ai_agent` sender type and `agents`/`tools`/`policies`
  apps exist only as placeholders.
- No customer-facing authentication portal; all Phase 3 APIs are
  workspace/support-side, authenticated through the existing staff user system.
- Ticket SLA/due-date automation is limited to storing `due_at`; no reminder
  or escalation behavior exists yet.
