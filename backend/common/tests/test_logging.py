"""Tests for the structured JSON log formatter."""

import json
import logging

from common.logging import JsonFormatter


def _make_record(**extra):
    record = logging.LogRecord(
        name="supportpilot",
        level=logging.INFO,
        pathname="test",
        lineno=1,
        msg="request_completed",
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


class TestJsonFormatter:
    def test_formats_record_as_valid_json(self):
        record = _make_record(request_id="abc-123", status=200)

        output = JsonFormatter().format(record)
        parsed = json.loads(output)

        assert parsed["message"] == "request_completed"
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "supportpilot"
        assert parsed["request_id"] == "abc-123"
        assert parsed["status"] == 200

    def test_includes_a_timestamp(self):
        record = _make_record()

        parsed = json.loads(JsonFormatter().format(record))

        assert "timestamp" in parsed

    def test_omits_internal_logrecord_bookkeeping_fields(self):
        record = _make_record()

        parsed = json.loads(JsonFormatter().format(record))

        assert "pathname" not in parsed
        assert "lineno" not in parsed
        assert "levelno" not in parsed
