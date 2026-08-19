"""``calendar.check_availability`` / ``calendar.create_booking`` tool
contract, timezone, and duplicate-booking tests (section 45-52, 93-95)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from django.utils import timezone

from customers.tests.factories import CustomerFactory
from integrations.errors import IntegrationRateLimitedError, IntegrationTimeoutError
from integrations.models import IntegrationProvider
from integrations.providers.base import AvailabilitySlot
from integrations.providers.fakes import FakeCalendarProvider
from tools.errors import ToolError
from tools.execution import execute_tool

from .factories import IntegrationConnectionFactory, allow_all_policy, bind_tool, running_run


def _setup(monkeypatch, *, fake=None, busy_slots=None):
    fake = fake or FakeCalendarProvider(busy_slots=busy_slots or [])
    run = running_run()
    bind_tool(run, "calendar.check_availability")
    bind_tool(run, "calendar.create_booking")
    allow_all_policy(run.workspace)  # this suite tests provider mechanics, not Phase 8 gating
    IntegrationConnectionFactory(
        workspace=run.workspace, provider=IntegrationProvider.GOOGLE_CALENDAR
    )
    monkeypatch.setattr("integrations.services.get_calendar_provider", lambda provider: fake)
    return run, fake


def _iso(dt: datetime) -> str:
    return dt.isoformat()


@pytest.mark.django_db(transaction=True)
class TestCheckAvailability:
    def test_free_window_returns_a_slot(self, monkeypatch):
        run, fake = _setup(monkeypatch)
        start = timezone.now() + timedelta(hours=2)
        end = start + timedelta(minutes=30)
        result = execute_tool(
            agent_run=run,
            tool_key="calendar.check_availability",
            arguments={"start": _iso(start), "end": _iso(end)},
        )
        assert len(result.output["slots"]) == 1

    def test_busy_window_returns_no_slots(self, monkeypatch):
        start = timezone.now() + timedelta(hours=2)
        end = start + timedelta(minutes=30)
        run, fake = _setup(monkeypatch, busy_slots=[AvailabilitySlot(start=start, end=end)])
        result = execute_tool(
            agent_run=run,
            tool_key="calendar.check_availability",
            arguments={"start": _iso(start), "end": _iso(end)},
        )
        assert result.output["slots"] == []

    def test_naive_datetime_is_rejected(self, monkeypatch):
        run, fake = _setup(monkeypatch)
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run,
                tool_key="calendar.check_availability",
                arguments={"start": "2030-01-01T10:00:00", "end": "2030-01-01T10:30:00"},
            )
        assert exc_info.value.code == "tool_invalid_input"

    def test_start_after_end_is_rejected(self, monkeypatch):
        run, fake = _setup(monkeypatch)
        start = timezone.now() + timedelta(hours=2)
        end = start - timedelta(minutes=30)
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run,
                tool_key="calendar.check_availability",
                arguments={"start": _iso(start), "end": _iso(end)},
            )
        assert exc_info.value.code == "tool_invalid_input"

    def test_beyond_scheduling_horizon_is_rejected(self, monkeypatch, settings):
        settings.INTEGRATIONS_CALENDAR_MAX_HORIZON_DAYS = 30
        run, fake = _setup(monkeypatch)
        start = timezone.now() + timedelta(days=400)
        end = start + timedelta(minutes=30)
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run,
                tool_key="calendar.check_availability",
                arguments={"start": _iso(start), "end": _iso(end)},
            )
        assert exc_info.value.code == "integration_invalid_request"
        assert fake.get_availability_call_count == 0

    def test_rate_limit_is_retried_then_succeeds(self, monkeypatch):
        fake = FakeCalendarProvider(availability_errors=[IntegrationRateLimitedError()])
        run, fake = _setup(monkeypatch, fake=fake)
        start = timezone.now() + timedelta(hours=2)
        end = start + timedelta(minutes=30)
        result = execute_tool(
            agent_run=run,
            tool_key="calendar.check_availability",
            arguments={"start": _iso(start), "end": _iso(end)},
        )
        assert len(result.output["slots"]) == 1
        assert fake.get_availability_call_count == 2


@pytest.mark.django_db(transaction=True)
class TestCreateBooking:
    def test_success(self, monkeypatch):
        run, fake = _setup(monkeypatch)
        customer = CustomerFactory(workspace=run.workspace, email="a@example.com")
        start = timezone.now() + timedelta(hours=2)
        end = start + timedelta(minutes=30)
        result = execute_tool(
            agent_run=run,
            tool_key="calendar.create_booking",
            arguments={
                "start": _iso(start),
                "end": _iso(end),
                "title": "Onboarding call",
                "customer_id": str(customer.id),
            },
        )
        assert result.output["status"] == "confirmed"
        assert fake.create_booking_call_count == 1

    def test_slot_conflict_is_normalized(self, monkeypatch):
        start = timezone.now() + timedelta(hours=2)
        end = start + timedelta(minutes=30)
        run, fake = _setup(monkeypatch, busy_slots=[AvailabilitySlot(start=start, end=end)])
        customer = CustomerFactory(workspace=run.workspace, email="a@example.com")
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run,
                tool_key="calendar.create_booking",
                arguments={
                    "start": _iso(start),
                    "end": _iso(end),
                    "title": "Onboarding call",
                    "customer_id": str(customer.id),
                },
            )
        assert exc_info.value.code == "calendar_slot_unavailable"

    def test_foreign_customer_is_rejected(self, monkeypatch):
        run, fake = _setup(monkeypatch)
        other_customer = CustomerFactory(email="a@example.com")  # different workspace
        start = timezone.now() + timedelta(hours=2)
        end = start + timedelta(minutes=30)
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run,
                tool_key="calendar.create_booking",
                arguments={
                    "start": _iso(start),
                    "end": _iso(end),
                    "title": "Onboarding call",
                    "customer_id": str(other_customer.id),
                },
            )
        assert exc_info.value.code == "customer_not_found"
        assert fake.create_booking_call_count == 0

    def test_repeated_call_with_same_idempotency_key_creates_one_booking(self, monkeypatch):
        run, fake = _setup(monkeypatch)
        customer = CustomerFactory(workspace=run.workspace, email="a@example.com")
        start = timezone.now() + timedelta(hours=2)
        end = start + timedelta(minutes=30)
        arguments = {
            "start": _iso(start),
            "end": _iso(end),
            "title": "Onboarding call",
            "customer_id": str(customer.id),
        }
        execute_tool(
            agent_run=run,
            tool_key="calendar.create_booking",
            arguments=arguments,
            idempotency_key="k1",
        )
        result2 = execute_tool(
            agent_run=run,
            tool_key="calendar.create_booking",
            arguments=arguments,
            idempotency_key="k1",
        )
        assert result2.reused is True
        assert fake.create_booking_call_count == 1

    def test_ambiguous_timeout_does_not_double_book(self, monkeypatch):
        start = timezone.now() + timedelta(hours=2)
        end = start + timedelta(minutes=30)
        fake = FakeCalendarProvider(booking_errors=[(IntegrationTimeoutError(), True)])
        run, fake = _setup(monkeypatch, fake=fake)
        customer = CustomerFactory(workspace=run.workspace, email="a@example.com")
        arguments = {
            "start": _iso(start),
            "end": _iso(end),
            "title": "Onboarding call",
            "customer_id": str(customer.id),
        }
        with pytest.raises(ToolError):
            execute_tool(
                agent_run=run,
                tool_key="calendar.create_booking",
                arguments=arguments,
                idempotency_key="k1",
            )
        assert fake.create_booking_call_count == 1
        result = execute_tool(
            agent_run=run,
            tool_key="calendar.create_booking",
            arguments=arguments,
            idempotency_key="k1",
        )
        assert result.execution.status == "succeeded"
        assert fake.create_booking_call_count == 1

    def test_beyond_scheduling_horizon_is_rejected(self, monkeypatch, settings):
        settings.INTEGRATIONS_CALENDAR_MAX_HORIZON_DAYS = 30
        run, fake = _setup(monkeypatch)
        customer = CustomerFactory(workspace=run.workspace, email="a@example.com")
        start = timezone.now() + timedelta(days=400)
        end = start + timedelta(minutes=30)
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run,
                tool_key="calendar.create_booking",
                arguments={
                    "start": _iso(start),
                    "end": _iso(end),
                    "title": "Onboarding call",
                    "customer_id": str(customer.id),
                },
            )
        assert exc_info.value.code == "integration_invalid_request"
        assert fake.create_booking_call_count == 0

    def test_title_too_long_is_rejected(self, monkeypatch, settings):
        settings.INTEGRATIONS_CALENDAR_MAX_TITLE_LENGTH = 10
        run, fake = _setup(monkeypatch)
        customer = CustomerFactory(workspace=run.workspace, email="a@example.com")
        start = timezone.now() + timedelta(hours=2)
        end = start + timedelta(minutes=30)
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run,
                tool_key="calendar.create_booking",
                arguments={
                    "start": _iso(start),
                    "end": _iso(end),
                    "title": "This title is way too long",
                    "customer_id": str(customer.id),
                },
            )
        assert exc_info.value.code == "integration_invalid_request"
        assert fake.create_booking_call_count == 0
