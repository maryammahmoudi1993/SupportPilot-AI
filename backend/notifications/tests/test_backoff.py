"""Exponential backoff boundary tests (Phase 10 Block 4, section 5)."""

from __future__ import annotations

from notifications.backoff import compute_retry_delay_seconds


def test_first_failure_schedules_base_delay():
    assert compute_retry_delay_seconds(attempt_number=1, base_delay_seconds=30) == 30


def test_second_failure_doubles_the_base_delay():
    assert compute_retry_delay_seconds(attempt_number=2, base_delay_seconds=30) == 60


def test_third_failure_quadruples_the_base_delay():
    assert compute_retry_delay_seconds(attempt_number=3, base_delay_seconds=30) == 120


def test_fourth_failure_continues_doubling():
    assert compute_retry_delay_seconds(attempt_number=4, base_delay_seconds=30) == 240


def test_delay_is_capped_at_the_configured_maximum():
    assert (
        compute_retry_delay_seconds(attempt_number=10, base_delay_seconds=30, max_delay_seconds=300)
        == 300
    )


def test_delay_exactly_at_the_cap_boundary_is_not_reduced_further():
    # base=30, attempt 4 -> 30*2**3 = 240, cap=240: exactly at the boundary.
    assert (
        compute_retry_delay_seconds(attempt_number=4, base_delay_seconds=30, max_delay_seconds=240)
        == 240
    )


def test_uses_server_settings_when_no_explicit_bounds_given(settings):
    settings.DELIVERY_RETRY_BASE_DELAY_SECONDS = 10
    settings.DELIVERY_RETRY_MAX_DELAY_SECONDS = 15
    assert compute_retry_delay_seconds(attempt_number=1) == 10
    # attempt 2 would be 20, capped to the server-owned maximum of 15.
    assert compute_retry_delay_seconds(attempt_number=2) == 15
