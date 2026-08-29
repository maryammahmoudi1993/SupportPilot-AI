"""Tests for inbound X-Request-ID validation (Phase 11 Block 2 remediation,
sections 2-3)."""

from __future__ import annotations

import uuid

from common.request_id import validate_request_id


class TestValidateRequestId:
    def test_none_generates_a_fresh_uuid4(self):
        result = validate_request_id(None)
        assert uuid.UUID(result).version == 4

    def test_empty_string_generates_a_fresh_uuid4(self):
        result = validate_request_id("")
        assert uuid.UUID(result).version == 4

    def test_a_normal_uuid4_is_reused_unchanged(self):
        inbound = str(uuid.uuid4())
        assert validate_request_id(inbound) == inbound

    def test_a_conventional_peer_correlation_id_is_reused_unchanged(self):
        inbound = "peer-service.request-42_ok"
        assert validate_request_id(inbound) == inbound

    def test_exactly_128_characters_is_accepted(self):
        inbound = "a" * 128
        assert validate_request_id(inbound) == inbound

    def test_over_128_characters_is_replaced(self):
        inbound = "a" * 129
        result = validate_request_id(inbound)
        assert result != inbound
        uuid.UUID(result)

    def test_newline_is_replaced(self):
        inbound = "safe-looking\nX-Injected-Header: evil"
        result = validate_request_id(inbound)
        assert result != inbound
        assert "\n" not in result
        uuid.UUID(result)

    def test_carriage_return_is_replaced(self):
        inbound = "safe\r\nSet-Cookie: pwned=1"
        result = validate_request_id(inbound)
        uuid.UUID(result)

    def test_tab_is_replaced(self):
        result = validate_request_id("has\ttab")
        uuid.UUID(result)

    def test_unicode_control_character_is_replaced(self):
        # U+200B zero-width space: not whitespace by regex \s rules but
        # outside the fixed allowed character set either way.
        result = validate_request_id("id​end")
        uuid.UUID(result)

    def test_null_byte_is_replaced(self):
        result = validate_request_id("id\x00end")
        uuid.UUID(result)

    def test_json_fragment_is_replaced(self):
        result = validate_request_id('{"admin": true}')
        uuid.UUID(result)

    def test_terminal_escape_sequence_is_replaced(self):
        result = validate_request_id("\x1b[31mred\x1b[0m")
        uuid.UUID(result)

    def test_credential_looking_marker_is_replaced_and_never_returned(self):
        marker = "SUPER_SECRET_REQUEST_ID_483921 Authorization: Bearer x"
        result = validate_request_id(marker)
        assert result != marker
        assert "SUPER_SECRET_REQUEST_ID_483921" not in result
        uuid.UUID(result)

    def test_plain_marker_alone_still_replaced_if_it_contains_a_space(self):
        # Spaces are outside the allowed character set even without any
        # other attack payload attached.
        result = validate_request_id("SUPER SECRET")
        uuid.UUID(result)
