"""The deterministic policy evaluator (section 6-9, 16, 25-29, 96-104)."""

from __future__ import annotations

import pytest

from policies.errors import PolicyEvaluationFailedError
from policies.evaluator import evaluate_policy
from policies.models import PolicyEffect
from policies.risk import assess_risk
from policies.tests.factories import PolicyRuleFactory, active_version_with_rules
from tools.contracts import RiskLevel, SideEffectType
from workspaces.tests.factories import WorkspaceFactory


def _risk(**overrides):
    defaults = dict(
        tool_key="payment.refund",
        base_risk=RiskLevel.CRITICAL,
        side_effect_type=SideEffectType.FINANCIAL,
        arguments={"amount_minor": 6000, "currency": "usd"},
    )
    defaults.update(overrides)
    args = defaults.pop("arguments")
    return assess_risk(arguments=args, **defaults)


@pytest.mark.django_db
class TestSystemDefault:
    def test_read_only_tool_allows_with_no_active_policy(self):
        risk = assess_risk(
            tool_key="customer.lookup",
            base_risk=RiskLevel.READ_ONLY,
            side_effect_type=SideEffectType.READ,
            arguments={},
        )
        result = evaluate_policy(
            tool_key="customer.lookup", risk=risk, arguments={}, active_version=None
        )
        assert result.decision == PolicyEffect.ALLOW
        assert result.policy_version is None

    def test_refund_below_auto_allow_threshold_allows(self, settings):
        settings.POLICIES_DEFAULT_REFUND_AUTO_ALLOW_MAX_MINOR = 5000
        settings.POLICIES_DEFAULT_REFUND_APPROVAL_MAX_MINOR = 50000
        risk = _risk(arguments={"amount_minor": 5000, "currency": "usd"})
        result = evaluate_policy(
            tool_key="payment.refund",
            risk=risk,
            arguments={"amount_minor": 5000, "currency": "usd"},
            active_version=None,
        )
        assert result.decision == PolicyEffect.ALLOW

    def test_refund_between_thresholds_requires_approval(self, settings):
        settings.POLICIES_DEFAULT_REFUND_AUTO_ALLOW_MAX_MINOR = 5000
        settings.POLICIES_DEFAULT_REFUND_APPROVAL_MAX_MINOR = 50000
        risk = _risk(arguments={"amount_minor": 10000, "currency": "usd"})
        result = evaluate_policy(
            tool_key="payment.refund",
            risk=risk,
            arguments={"amount_minor": 10000, "currency": "usd"},
            active_version=None,
        )
        assert result.decision == PolicyEffect.REQUIRE_APPROVAL
        assert result.required_role  # derived from risk

    def test_refund_above_maximum_denies(self, settings):
        settings.POLICIES_DEFAULT_REFUND_AUTO_ALLOW_MAX_MINOR = 5000
        settings.POLICIES_DEFAULT_REFUND_APPROVAL_MAX_MINOR = 50000
        risk = _risk(arguments={"amount_minor": 100000, "currency": "usd"})
        result = evaluate_policy(
            tool_key="payment.refund",
            risk=risk,
            arguments={"amount_minor": 100000, "currency": "usd"},
            active_version=None,
        )
        assert result.decision == PolicyEffect.DENY

    def test_refund_unconfigured_currency_requires_approval_not_the_usd_threshold(self, settings):
        settings.POLICIES_DEFAULT_REFUND_AUTO_ALLOW_MAX_MINOR = 5000
        risk = _risk(arguments={"amount_minor": 100, "currency": "eur"})
        result = evaluate_policy(
            tool_key="payment.refund",
            risk=risk,
            arguments={"amount_minor": 100, "currency": "eur"},
            active_version=None,
        )
        assert result.decision == PolicyEffect.REQUIRE_APPROVAL

    def test_external_write_requires_approval(self):
        risk = assess_risk(
            tool_key="calendar.create_booking",
            base_risk=RiskLevel.HIGH,
            side_effect_type=SideEffectType.EXTERNAL_WRITE,
            arguments={},
        )
        result = evaluate_policy(
            tool_key="calendar.create_booking", risk=risk, arguments={}, active_version=None
        )
        assert result.decision == PolicyEffect.REQUIRE_APPROVAL

    def test_internal_write_allows(self):
        risk = assess_risk(
            tool_key="ticket.create",
            base_risk=RiskLevel.MEDIUM,
            side_effect_type=SideEffectType.INTERNAL_WRITE,
            arguments={},
        )
        result = evaluate_policy(
            tool_key="ticket.create", risk=risk, arguments={}, active_version=None
        )
        assert result.decision == PolicyEffect.ALLOW

    def test_determinism_same_inputs_same_decision(self):
        risk = _risk()
        args = {"amount_minor": 6000, "currency": "usd"}
        first = evaluate_policy(
            tool_key="payment.refund", risk=risk, arguments=args, active_version=None
        )
        second = evaluate_policy(
            tool_key="payment.refund", risk=risk, arguments=args, active_version=None
        )
        assert first.decision == second.decision
        assert first.decision_code == second.decision_code


@pytest.mark.django_db
class TestWorkspacePolicy:
    def test_rule_matched_by_tool_key_wins_over_default(self):
        workspace = WorkspaceFactory()
        version = active_version_with_rules(
            workspace=workspace,
            rules=[dict(name="deny-refunds", tool_key="payment.refund", effect=PolicyEffect.DENY)],
        )
        risk = _risk(
            arguments={"amount_minor": 1, "currency": "usd"}
        )  # would auto-allow by default
        result = evaluate_policy(
            tool_key="payment.refund",
            risk=risk,
            arguments={"amount_minor": 1, "currency": "usd"},
            active_version=version,
        )
        assert result.decision == PolicyEffect.DENY
        assert result.policy_version == version

    def test_precedence_deny_beats_require_approval_beats_allow(self):
        workspace = WorkspaceFactory()
        version = active_version_with_rules(
            workspace=workspace,
            rules=[
                dict(name="allow-all", priority=0, effect=PolicyEffect.ALLOW),
                dict(
                    name="approve-refunds",
                    priority=1,
                    tool_key="payment.refund",
                    effect=PolicyEffect.REQUIRE_APPROVAL,
                ),
                dict(
                    name="deny-refunds",
                    priority=2,
                    tool_key="payment.refund",
                    effect=PolicyEffect.DENY,
                ),
            ],
        )
        risk = _risk()
        result = evaluate_policy(
            tool_key="payment.refund",
            risk=risk,
            arguments={"amount_minor": 6000, "currency": "usd"},
            active_version=version,
        )
        assert result.decision == PolicyEffect.DENY

    def test_disabled_rule_never_matches(self):
        workspace = WorkspaceFactory()
        version = active_version_with_rules(
            workspace=workspace,
            rules=[
                dict(
                    name="deny-refunds",
                    tool_key="payment.refund",
                    effect=PolicyEffect.DENY,
                    enabled=False,
                )
            ],
        )
        risk = _risk(arguments={"amount_minor": 100000, "currency": "usd"})
        result = evaluate_policy(
            tool_key="payment.refund",
            risk=risk,
            arguments={"amount_minor": 100000, "currency": "usd"},
            active_version=version,
        )
        # falls through to no-match -> system default (deny, since > max)
        assert result.decision == PolicyEffect.DENY
        assert result.decision_code.startswith("no_matching_rule_fallback")

    def test_no_matching_rule_falls_back_to_system_default_explicitly(self):
        workspace = WorkspaceFactory()
        version = active_version_with_rules(
            workspace=workspace,
            rules=[dict(name="unrelated", tool_key="ticket.create", effect=PolicyEffect.DENY)],
        )
        risk = assess_risk(
            tool_key="customer.lookup",
            base_risk=RiskLevel.READ_ONLY,
            side_effect_type=SideEffectType.READ,
            arguments={},
        )
        result = evaluate_policy(
            tool_key="customer.lookup", risk=risk, arguments={}, active_version=version
        )
        assert result.decision == PolicyEffect.ALLOW
        assert "no_matching_rule_fallback" in result.decision_code

    def test_condition_predicate_gates_the_rule(self):
        workspace = WorkspaceFactory()
        version = active_version_with_rules(
            workspace=workspace,
            rules=[
                dict(
                    name="deny-large-refunds",
                    tool_key="payment.refund",
                    effect=PolicyEffect.DENY,
                    condition_config={"all": [{"predicate": "amount_minor_gt", "value": 1000}]},
                )
            ],
        )
        small = evaluate_policy(
            tool_key="payment.refund",
            risk=_risk(arguments={"amount_minor": 500, "currency": "usd"}),
            arguments={"amount_minor": 500, "currency": "usd"},
            active_version=version,
        )
        large = evaluate_policy(
            tool_key="payment.refund",
            risk=_risk(arguments={"amount_minor": 5000, "currency": "usd"}),
            arguments={"amount_minor": 5000, "currency": "usd"},
            active_version=version,
        )
        # small doesn't match the rule -> falls back to system default (allow, <=5000)
        assert small.decision == PolicyEffect.ALLOW
        assert large.decision == PolicyEffect.DENY

    def test_unknown_predicate_in_stored_rule_fails_closed(self):
        workspace = WorkspaceFactory()
        version = active_version_with_rules(workspace=workspace, rules=[])
        PolicyRuleFactory(
            policy_version=version,
            name="corrupt",
            tool_key="payment.refund",
            effect=PolicyEffect.ALLOW,
            condition_config={"all": [{"predicate": "does_not_exist"}]},
        )
        with pytest.raises(PolicyEvaluationFailedError):
            evaluate_policy(
                tool_key="payment.refund",
                risk=_risk(),
                arguments={"amount_minor": 6000, "currency": "usd"},
                active_version=version,
            )

    def test_risk_levels_filter_excludes_non_matching_risk(self):
        workspace = WorkspaceFactory()
        version = active_version_with_rules(
            workspace=workspace,
            rules=[
                dict(
                    name="deny-only-low",
                    tool_key="payment.refund",
                    effect=PolicyEffect.DENY,
                    risk_levels=["low"],
                )
            ],
        )
        result = evaluate_policy(
            tool_key="payment.refund",
            risk=_risk(),  # critical, not "low"
            arguments={"amount_minor": 6000, "currency": "usd"},
            active_version=version,
        )
        # rule doesn't match -> falls back to the system default.
        assert "no_matching_rule_fallback" in result.decision_code

    def test_side_effect_types_filter_excludes_non_matching_type(self):
        workspace = WorkspaceFactory()
        version = active_version_with_rules(
            workspace=workspace,
            rules=[
                dict(
                    name="deny-reads-only",
                    tool_key="payment.refund",
                    effect=PolicyEffect.DENY,
                    side_effect_types=["read"],
                )
            ],
        )
        result = evaluate_policy(
            tool_key="payment.refund",
            risk=_risk(),  # side_effect_type is "financial", not "read"
            arguments={"amount_minor": 6000, "currency": "usd"},
            active_version=version,
        )
        assert "no_matching_rule_fallback" in result.decision_code

    def test_malformed_condition_config_all_not_a_list_fails_closed(self):
        workspace = WorkspaceFactory()
        version = active_version_with_rules(workspace=workspace, rules=[])
        PolicyRuleFactory(
            policy_version=version,
            name="malformed",
            tool_key="payment.refund",
            effect=PolicyEffect.ALLOW,
            condition_config={"all": "not-a-list"},
        )
        with pytest.raises(PolicyEvaluationFailedError):
            evaluate_policy(
                tool_key="payment.refund",
                risk=_risk(),
                arguments={"amount_minor": 6000, "currency": "usd"},
                active_version=version,
            )

    def test_malformed_condition_entry_not_a_dict_fails_closed(self):
        workspace = WorkspaceFactory()
        version = active_version_with_rules(workspace=workspace, rules=[])
        PolicyRuleFactory(
            policy_version=version,
            name="malformed",
            tool_key="payment.refund",
            effect=PolicyEffect.ALLOW,
            condition_config={"all": ["not-a-dict"]},
        )
        with pytest.raises(PolicyEvaluationFailedError):
            evaluate_policy(
                tool_key="payment.refund",
                risk=_risk(),
                arguments={"amount_minor": 6000, "currency": "usd"},
                active_version=version,
            )

    def test_rule_required_role_and_ttl_override_defaults(self):
        workspace = WorkspaceFactory()
        version = active_version_with_rules(
            workspace=workspace,
            rules=[
                dict(
                    name="approve-refunds",
                    tool_key="payment.refund",
                    effect=PolicyEffect.REQUIRE_APPROVAL,
                    required_role="owner",
                    approval_ttl_seconds=120,
                )
            ],
        )
        result = evaluate_policy(
            tool_key="payment.refund",
            risk=_risk(),
            arguments={"amount_minor": 6000, "currency": "usd"},
            active_version=version,
        )
        assert result.required_role == "owner"
        assert result.approval_ttl_seconds == 120
