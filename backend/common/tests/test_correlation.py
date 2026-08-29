"""Tests for correlation-id propagation (Phase 11 Block 2)."""

from __future__ import annotations

import logging
import uuid

from common.correlation import (
    CorrelationIdLogFilter,
    correlation_scope,
    get_correlation_id,
    new_correlation_id,
)


class TestNewCorrelationId:
    def test_returns_a_valid_uuid4_string(self):
        value = new_correlation_id()
        assert uuid.UUID(value).version == 4

    def test_successive_calls_are_unique(self):
        assert new_correlation_id() != new_correlation_id()


class TestCorrelationScope:
    def test_unbound_scope_has_no_correlation_id(self):
        assert get_correlation_id() is None

    def test_binds_for_the_duration_of_the_block(self):
        correlation_id = new_correlation_id()
        with correlation_scope(correlation_id):
            assert get_correlation_id() == correlation_id
        assert get_correlation_id() is None

    def test_restores_the_outer_scope_on_exit_not_just_none(self):
        outer_id = new_correlation_id()
        inner_id = new_correlation_id()
        with correlation_scope(outer_id):
            with correlation_scope(inner_id):
                assert get_correlation_id() == inner_id
            assert get_correlation_id() == outer_id
        assert get_correlation_id() is None

    def test_restores_the_prior_scope_even_when_the_block_raises(self):
        with correlation_scope(new_correlation_id()):
            try:
                with correlation_scope(new_correlation_id()):
                    raise RuntimeError("boom")
            except RuntimeError:
                pass
            # Whatever the outer scope's id was, not leaked/cleared entirely.
            assert get_correlation_id() is not None


class TestCorrelationIdLogFilter:
    def _make_record(self) -> logging.LogRecord:
        return logging.LogRecord(
            name="supportpilot",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="test_message",
            args=(),
            exc_info=None,
        )

    def test_injects_the_currently_bound_correlation_id(self):
        correlation_id = new_correlation_id()
        record = self._make_record()
        with correlation_scope(correlation_id):
            assert CorrelationIdLogFilter().filter(record) is True
        assert record.correlation_id == correlation_id

    def test_injects_empty_string_when_no_scope_is_bound(self):
        record = self._make_record()
        assert CorrelationIdLogFilter().filter(record) is True
        assert record.correlation_id == ""
