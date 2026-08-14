"""Tests for the sensitive-field redaction helper."""

from common.redaction import REDACTED, is_sensitive_key, redact


class TestIsSensitiveKey:
    def test_matches_known_markers_case_insensitively(self):
        assert is_sensitive_key("Password")
        assert is_sensitive_key("STRIPE_SECRET_KEY")
        assert is_sensitive_key("refresh_token")
        assert is_sensitive_key("Authorization")

    def test_does_not_match_ordinary_field_names(self):
        assert not is_sensitive_key("email")
        assert not is_sensitive_key("order_id")
        assert not is_sensitive_key("amount")

    def test_non_string_keys_are_never_sensitive(self):
        assert not is_sensitive_key(42)
        assert not is_sensitive_key(None)


class TestRedact:
    def test_redacts_sensitive_top_level_keys(self):
        payload = {"email": "a@example.com", "password": "hunter2"}

        result = redact(payload)

        assert result == {"email": "a@example.com", "password": REDACTED}

    def test_redacts_sensitive_keys_nested_inside_dicts(self):
        payload = {"customer": {"email": "a@example.com", "api_key": "sk-live-123"}}

        result = redact(payload)

        assert result["customer"]["api_key"] == REDACTED
        assert result["customer"]["email"] == "a@example.com"

    def test_redacts_sensitive_keys_inside_lists_of_dicts(self):
        payload = {"tool_calls": [{"name": "execute_refund", "auth_token": "abc"}]}

        result = redact(payload)

        assert result["tool_calls"][0]["auth_token"] == REDACTED
        assert result["tool_calls"][0]["name"] == "execute_refund"

    def test_extra_keys_are_redacted_by_exact_match(self):
        payload = {"card_last_four": "4242", "order_id": "48321"}

        result = redact(payload, extra_keys=frozenset({"card_last_four"}))

        assert result["card_last_four"] == REDACTED
        assert result["order_id"] == "48321"

    def test_non_dict_values_pass_through_unchanged(self):
        assert redact("hello") == "hello"
        assert redact(42) == 42
        assert redact(None) is None

    def test_does_not_mutate_the_original_payload(self):
        payload = {"password": "hunter2"}

        redact(payload)

        assert payload == {"password": "hunter2"}
