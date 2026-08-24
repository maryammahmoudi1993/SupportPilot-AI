# Bounded Tool Orchestration

Phase 9 Block 3 extends an `AgentRun` with a bounded, sequential
LLM → tool → LLM cycle. It consumes the existing Phase 6–8 tool executor and does not create a
second execution or authorization system.

## Catalog authority

`agents.tool_catalog.get_bound_tool_descriptors` derives the provider-facing catalog only from a
published `AgentVersion`, its workspace-scoped enabled `ToolBinding` rows, active
`ToolDefinition` mirrors, and the trusted in-process registry. A missing registry implementation
or handler-key mismatch fails closed. Unbound, disabled, inactive, cross-tenant, and dangerous
unregistered tools are absent.

JSON Schema comes directly from each registered `ToolSpec.input_model`. Server-owned workspace,
run, credential, risk, policy, approval, timeout, and retry fields are not exposed. The internal
`ToolDescriptor` and `NormalizedToolCall` contracts contain no vendor SDK types; adapters perform
vendor-specific naming and JSON argument parsing at their boundary.

## Cycle and termination

Each model turn may propose several calls, but only the first is considered and at most one tool
executes. Remaining calls are ignored and only their count is traced. Tools always execute
sequentially because each result can change the next model decision, policy state, or approval
branch.

Every successful or safely denied/failed tool outcome routes through `check_budget` before another
model call. Model calls, meaningful runtime steps, tokens, cost, and the original monotonic
deadline accumulate across turns. The deadline is never reset. The Phase 6 counter remains defined
as actual trusted handler attempts: unknown, unbound, disabled, invalid-input, policy-denied, and
approval-paused requests do not increment `AgentRun.tool_call_count`.

Exact model, tool, step, token, cost, and wall-time boundaries terminate the graph. Tool-budget
enforcement remains inside `execute_tool`, while all model-loop paths pass through the runtime
budget node. Idempotency keys are server-generated from the run, model-turn number, canonical tool
key, and canonical arguments; provider call IDs are not trusted as replay authority.

## Tool-result trust boundary

Tool output is typed and redacted by the existing executor, then rendered as bounded untrusted
data between `TOOL RESULT — UNTRUSTED EXTERNAL DATA` and `END TOOL RESULT`. The closing delimiter
is preserved even when data is truncated. Safe business failures, policy denials, and rejected
model requests can be supplied to a follow-up model turn using stable error codes without private
policy details. Configuration, persistence, and graph-corruption failures terminate safely.

A `REQUIRE_APPROVAL` decision creates/reuses the existing `ApprovalRequest`, moves the run to
`WAITING_FOR_APPROVAL`, and exits without invoking the handler or scheduling another model call.
See `approval-resume-continuations.md` for how Block 4 completes the approve, reject, expiry, and
cancellation continuations out of this pause.
