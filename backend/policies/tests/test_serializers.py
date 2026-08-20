"""PolicyRuleCreateSerializer.condition_config validation (section 80-81)."""

from __future__ import annotations

from policies.serializers import PolicyRuleCreateSerializer


def _base_data(**overrides):
    data = {"name": "r1", "priority": 0, "effect": "allow"}
    data.update(overrides)
    return data


class TestConditionConfigValidation:
    def test_none_defaults_to_empty_all(self):
        serializer = PolicyRuleCreateSerializer(data=_base_data())
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["condition_config"] == {"all": []}

    def test_non_dict_is_rejected(self):
        serializer = PolicyRuleCreateSerializer(
            data=_base_data(condition_config=["not", "a", "dict"])
        )
        assert not serializer.is_valid()

    def test_extra_top_level_key_is_rejected(self):
        serializer = PolicyRuleCreateSerializer(
            data=_base_data(condition_config={"all": [], "extra": 1})
        )
        assert not serializer.is_valid()

    def test_all_must_be_a_list(self):
        serializer = PolicyRuleCreateSerializer(
            data=_base_data(condition_config={"all": "not-a-list"})
        )
        assert not serializer.is_valid()

    def test_too_many_entries_is_rejected(self):
        entries = [{"predicate": "tool_is", "value": "x"} for _ in range(11)]
        serializer = PolicyRuleCreateSerializer(data=_base_data(condition_config={"all": entries}))
        assert not serializer.is_valid()

    def test_entry_without_predicate_key_is_rejected(self):
        serializer = PolicyRuleCreateSerializer(
            data=_base_data(condition_config={"all": [{"value": "x"}]})
        )
        assert not serializer.is_valid()

    def test_non_dict_entry_is_rejected(self):
        serializer = PolicyRuleCreateSerializer(
            data=_base_data(condition_config={"all": ["not-a-dict"]})
        )
        assert not serializer.is_valid()

    def test_unknown_predicate_is_rejected(self):
        serializer = PolicyRuleCreateSerializer(
            data=_base_data(condition_config={"all": [{"predicate": "nonexistent"}]})
        )
        assert not serializer.is_valid()

    def test_known_predicate_passes(self):
        serializer = PolicyRuleCreateSerializer(
            data=_base_data(
                condition_config={"all": [{"predicate": "tool_is", "value": "payment.refund"}]}
            )
        )
        assert serializer.is_valid(), serializer.errors
