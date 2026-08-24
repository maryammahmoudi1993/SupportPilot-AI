# Conversation Context and Tenant-Scoped RAG

Phase 9 Block 2 adds a bounded context pipeline to the existing agent runtime. It does not
change the policy, approval, tool-execution, or approval-resume boundaries.

## Conversation boundary

`agents.context.build_conversation_context` accepts a trusted workspace, conversation, and
`AgentRun.trigger_message`. The trigger must be a non-empty inbound customer message belonging
to both the workspace and conversation. Context loading reuses the conversation selector and
applies the workspace predicate again as defense in depth.

Only inbound customer messages and outbound human/AI replies receive normalized `user` and
`assistant` roles. Internal messages, system events, and unknown direction/type combinations are
excluded. History keeps the newest safe messages, drops the oldest first, and always includes the
trigger exactly once. The trigger consumes the character budget first. Individual content and the
aggregate are therefore bounded without a tokenizer dependency.

The defaults are `AGENTS_CONTEXT_MAX_MESSAGES=20` and
`AGENTS_CONTEXT_MAX_CHARACTERS=12000`. Character counting is the sum of normalized message body
lengths; provider wrappers and reference labels are not included in that history count.

## Retrieval boundary

`agents.rag.retrieve_agent_knowledge` calls the Phase 4 `search_knowledge` service. It does not
perform vector queries, embedding construction, or tenant filtering itself. The query is the
trimmed trigger body, deterministically limited by Phase 4's maximum query length. Workspace and
actor come from the claimed `AgentRun`, never customer text or model output.

`AGENTS_RAG_TOP_K` must remain within `KNOWLEDGE_MAX_TOP_K` and defaults to 5.
`AGENTS_RAG_MAX_CHARACTERS` defaults to 8000. Highest-ranked chunks are retained first; the final
retained chunk may be right-truncated. Omitted chunks receive no citation. Zero results are valid
and still allow the model call. Unexpected retrieval errors safely fail the run with
`knowledge_retrieval_failed`; raw infrastructure exceptions are logged server-side but are not
persisted as customer-safe failure text.

## Untrusted reference material

The published `AgentVersion.system_prompt` remains a separate, first system message. Retrieved
text is placed in a later user-role message between explicit `REFERENCE MATERIAL` and
`END REFERENCE MATERIAL` markers with an instruction that it cannot change workspace scope,
credentials, tool access, policy, or approvals. Application boundaries remain authoritative even
if a document contains prompt-injection text.

The context pipeline never queries `IntegrationConnection`, so encrypted credentials and
decrypted provider secrets cannot enter the model request. User-managed knowledge is intentionally
model-visible and is not treated as an application credential merely because its text resembles
one.

## Citation trust

Citation metadata is built only from Phase 4 retrieval results actually supplied to the model.
Each record contains safe chunk, document, source, title, positional citation, and truncation
fields. Scores, vectors, database details, and model-generated citation IDs are excluded. On a
successful knowledge response, these records are stored under `Message.metadata.citations`; no
new table is required. A source the model merely names can never become a trusted citation.

Agent steps record only counts, truncation flags, retrieval/source identifiers, character sizes,
and duration. Full prompts, conversations, retrieved text, provider reasoning, and chain-of-thought
are not persisted in operational trace metadata.
