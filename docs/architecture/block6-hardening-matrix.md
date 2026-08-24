# Phase 9 — Block 6 hardening matrix

Block 6 is an adversarial audit of the orchestration built across Blocks
1–5, not a new feature block. This document maps every required
adversarial/concurrency/E2E scenario to the test(s) that already prove it —
most of them written during Blocks 1–5 as part of normal feature
development — plus the small set of genuinely new full-stack tests Block 6
added in `agents/tests/test_orchestration_hardening.py`. No production
defect was found during this audit; the changes below are test-only.

## Tenant isolation

| Attack | Proof |
| --- | --- |
| Foreign trigger message | `agents/tests/test_orchestration.py::TestStartSupportAgentRun::test_a_message_from_another_workspace_is_rejected`, `agents/tests/test_tool_integration.py::TestOrchestrationGuards::test_foreign_trigger_is_rejected_before_retrieval_or_llm` |
| Foreign conversation | `agents/tests/test_orchestration.py::TestStartSupportAgentRun::test_a_message_from_another_conversation_is_rejected` |
| Foreign perfect-match RAG | `agents/tests/test_tool_integration.py::TestKnowledgeOrchestration::test_cross_tenant_perfect_match_never_reaches_request_trace_or_citations` |
| Foreign customer/ticket/order resource | `customers/tests/test_cross_tenant_matrix.py`, `tickets/tests/test_cross_tenant_matrix.py`, `integrations/tests/test_security.py::TestSpoofingAttempts` |
| Foreign integration connection | `integrations/tests/test_security.py::TestSpoofingAttempts::test_no_tool_accepts_a_connection_identifier_argument` |
| Foreign approval | `approvals/tests/test_views.py::TestApprovalCrossTenant` |
| Foreign handoff | `tickets/tests/test_handoffs.py::TestHumanHandoffApi::test_foreign_workspace_handoff_id_404s` |
| Foreign/unbound ToolBinding | `agents/tests/test_tool_integration.py::TestUnboundToolAgentIntegration`, `agents/tests/test_multi_turn_tools.py::test_disabled_bound_tool_is_hidden_and_blocked_if_requested` |

## Injection hardening

| Attack | Proof |
| --- | --- |
| Customer prompt injection | `agents/tests/test_tool_integration.py::TestKnowledgeOrchestration::test_prompt_injection_has_no_application_authority_and_secrets_are_not_loaded` |
| RAG document injection | same test, plus `agents/tests/test_rag.py` |
| Tool-result injection | `agents/tests/test_multi_turn_tools.py::test_tool_result_prompt_injection_remains_delimited_untrusted_data` |
| Approval-comment injection | `approvals/tests/test_views.py::TestApprovalDecisionAPI::test_comment_is_bounded_length`; the comment is stored on `ApprovalDecision.safe_comment` only and is never read back into any provider-facing context — no code path passes it to `LLMRequest`. |
| Workspace/policy/approval spoof in model arguments | `agents/tests/test_multi_turn_tools.py::test_malformed_and_spoofed_arguments_never_reach_handler`, `agents/tests/test_security.py::TestBudgetTamperingPrevention` |
| Assignee/role/ticket spoof via handoff request | structural: `NormalizedHandoffRequest` has no such fields at all (`agents/providers/schemas.py`) |
| Dangerous/unknown tool | `tools/tests/test_registry.py::TestDefaultRegistryDangerousToolsAbsent`, `agents/tests/test_tool_integration.py::TestUnknownToolAgentIntegration`, and (new, full orchestration) `agents/tests/test_orchestration_hardening.py::TestDangerousUnknownToolFullOrchestration` |

## Idempotency / concurrency

| Race | Proof |
| --- | --- |
| Duplicate trigger message | `agents/tests/test_orchestration.py::TestStartSupportAgentRun::test_a_duplicate_trigger_message_reuses_the_same_run` |
| Duplicate AgentRun claim (real threads) | **new** — `TestFullStackConcurrencyRaces::test_two_workers_claiming_the_same_pending_run_execute_the_model_once` |
| Duplicate final Message | `agents/tests/test_orchestration.py::TestFinalResponsePersistence::test_redelivered_execution_does_not_duplicate_the_message` |
| Duplicate tool execution claim | `agents/tests/test_runtime_execution.py::TestScenarioEDuplicateExecutionClaim` |
| Duplicate refund delivery (real threads) | **new** — `TestFullStackConcurrencyRaces::test_duplicate_refund_resume_delivery_executes_the_provider_once` |
| Duplicate booking delivery | same idempotency mechanism as refund, covered structurally by `tools/tests/test_resume_after_approval.py::TestResumeRaceAndReplay` |
| Double approve (real threads) | `approvals/tests/test_services.py::TestConcurrency::test_two_concurrent_approves_produce_exactly_one_decision` |
| Approve vs reject (real threads) | `approvals/tests/test_services.py::TestConcurrency::test_approve_vs_reject_race_produces_one_final_status` |
| Approve vs cancel, full orchestration (real threads) | **new** — `TestFullStackConcurrencyRaces::test_approve_vs_cancel_race_through_full_orchestration_is_coherent` |
| Approve vs expiry | `approvals/tests/test_services.py::TestDecideApproval::test_decision_after_expiry_fails_safely` |
| Double handoff completion (real threads) | **new** — `TestFullStackConcurrencyRaces::test_double_handoff_completion_delivery_creates_one_handoff_and_message` |
| Handoff vs cancel (real threads) | **new** — `TestFullStackConcurrencyRaces::test_handoff_vs_cancel_race_is_never_incoherent` |
| Duplicate resume dispatch | `approvals/tests/test_tasks.py::TestResumeTask`, `tools/tests/test_resume_after_approval.py::TestResumeRaceAndReplay` |
| Crash after tool success / after final Message / after handoff / after approval decision | covered structurally: every terminal write happens inside one `select_for_update`-guarded transaction (`_complete_run`, `_complete_run_as_handoff`, `resume_after_approval`'s claim) — a crash before commit leaves nothing to replay-detect, and a crash after commit is indistinguishable from ordinary redelivery, already exercised by the redelivery tests above. |

## Terminal-state / budget hardening

| Attack | Proof |
| --- | --- |
| Reopen SUCCEEDED/FAILED/CANCELLED/BUDGET_EXCEEDED/HANDED_OFF | `agents/tests/test_services_lifecycle.py::TestCancelAgentRun::test_terminal_run_cannot_be_cancelled_again` (parametrized, HANDED_OFF added in Block 6), `agents/tests/test_runtime_execution.py::TestScenarioGTerminalStateProtection` |
| Stale WAITING_FOR_APPROVAL worker / stale original worker | `agents/services._claim_run_for_resume` is the single point of idempotency for all three decision outcomes — exercised by `approvals/tests/test_tasks.py::TestResumeTask` |
| `max_model_calls` / `max_tool_calls` / `max_steps` / token budget | `agents/tests/test_multi_turn_tools.py` (`test_exact_tool_budget_executes_two_and_blocks_third`, `test_exact_model_budget_never_schedules_a_fourth_turn`, `test_step_budget_is_rechecked_before_a_post_tool_model_turn`), `agents/tests/test_runtime_budgets.py` |
| Budget preserved across approval resume | `agents/services._continue_run_after_resumed_tool` reuses the same run's persisted counters (no reset) — exercised end-to-end by the new Scenario K test below |
| No extra LLM call for handoff acknowledgement | `agents/tests/test_handoff_orchestration.py::TestExplicitHandoffRequest::test_no_extra_model_call_is_spent_formulating_the_acknowledgement`, reconfirmed for the approval-then-handoff combination by the new Scenario K test |

## Failure hardening

| Failure | Proof |
| --- | --- |
| Provider rate-limit / timeout / temporary-outage exhaustion → handoff | `agents/tests/test_handoff_orchestration.py::TestFailureClassification::test_provider_retry_exhaustion_becomes_a_handoff_end_to_end` |
| Provider auth failure → FAILED, never handoff | `test_provider_authentication_failure_fails_the_run_never_a_handoff` |
| Provider config failure → FAILED | `agents/tests/test_runtime_execution.py::TestProviderVersionMismatch` |
| Safe business tool failure → no escalation | `test_safe_business_tool_failure_does_not_escalate_by_default` |
| RAG infrastructure failure | `agents/tests/test_tool_integration.py::TestKnowledgeOrchestration::test_retrieval_failure_fails_safely_without_model_or_output` |

## Full end-to-end flow matrix

| Scenario | Proof |
| --- | --- |
| A — knowledge only | `agents/tests/test_tool_integration.py::TestKnowledgeOrchestration::test_knowledge_answer_persists_only_trusted_real_citations` |
| B — read-only tool | `agents/tests/test_tool_integration.py::TestFullToolRoundtrip` |
| C — multi-tool | `agents/tests/test_multi_turn_tools.py::test_two_tools_execute_sequentially_then_one_final_response` |
| D — policy deny | `agents/tests/test_multi_turn_tools.py::test_policy_deny_has_no_side_effect_and_allows_safe_follow_up` |
| E — approval approve + resume | `tools/tests/test_resume_after_approval.py::TestResumeRaceAndReplay::test_second_resume_call_after_success_replays_the_stored_result` + `approvals/tests/test_tasks.py::TestResumeTask` (tool-level); full graph continuation covered by `_continue_run_after_resumed_tool` and reconfirmed transitively by Scenario K below |
| F — approval rejected | `tools/tests/test_resume_after_approval.py::TestResumeRaceAndReplay::test_second_resume_call_after_rejection_replays_the_rejection` |
| G — approval expired | `approvals/tests/test_services.py::TestDecideApproval::test_decision_after_expiry_fails_safely`, `approvals/tests/test_tasks.py::TestExpireTask` |
| H — two approvals in one run | structural: each `ToolExecution` gets its own `ApprovalRequest` (`approvals/tests/test_services.py::TestApprovalCreation::test_exactly_one_approval_request_per_tool_execution`) |
| I — explicit human handoff | `agents/tests/test_handoff_orchestration.py::TestExplicitHandoffRequest` |
| J — multi-tool then handoff | `agents/tests/test_handoff_orchestration.py::TestMultiTurnThenHandoff` |
| K — approval then handoff | **new** — `agents/tests/test_orchestration_hardening.py::TestE2EScenarioKApprovalThenHandoff` |
| L — retry-exhausted provider handoff | `agents/tests/test_handoff_orchestration.py::TestFailureClassification::test_provider_retry_exhaustion_becomes_a_handoff_end_to_end` |
| M — internal/config failure | `agents/tests/test_handoff_orchestration.py::TestFailureClassification::test_provider_authentication_failure_fails_the_run_never_a_handoff` |
| Budget exhaustion | `agents/tests/test_multi_turn_tools.py`, `agents/tests/test_runtime_execution.py::TestScenarioCBudgetExceeded` |

## What Block 6 added

* `agents/tests/test_orchestration_hardening.py` — five real multi-threaded
  concurrency tests against actual PostgreSQL row locks (not sequential
  replay), the missing approval-then-handoff end-to-end scenario, a
  live-RBAC-at-decision-time regression, a full-orchestration dangerous-tool
  attack, and a secret-leakage check against a real stored integration
  credential.
* `HANDED_OFF` added to the existing terminal-state reopen parametrize in
  `agents/tests/test_services_lifecycle.py`.

No production code changed as a result of this audit — every adversarial
scenario exercised either an invariant Blocks 1–5 already enforced
correctly, or (for the concurrency tests) confirmed that the existing
`select_for_update` + status-guard pattern used throughout `agents/services.py`
and `tickets/services.py` genuinely serializes under real thread
contention, not just under test-only sequential calls.
