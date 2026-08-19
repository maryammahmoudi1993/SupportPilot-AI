"""Google Calendar adapter SDK-boundary tests (section 45-52, 93, 95)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from googleapiclient.errors import HttpError

from integrations.errors import (
    CalendarSlotUnavailableError,
    IntegrationAuthenticationFailedError,
    IntegrationInvalidRequestError,
    IntegrationMalformedResponseError,
    IntegrationPermissionDeniedError,
    IntegrationRateLimitedError,
    IntegrationTemporarilyUnavailableError,
)
from integrations.providers.google_calendar import GoogleCalendarProvider

CREDENTIALS = {"service_account_info": {"type": "service_account"}}


class _FakeHttpResponse:
    def __init__(self, status: int) -> None:
        self.status = status
        self.reason = "error"


def _http_error(status: int, content: bytes = b"{}") -> HttpError:
    return HttpError(_FakeHttpResponse(status), content)


class _FakeExecutable:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error

    def execute(self):
        if self._error is not None:
            raise self._error
        return self._result


class _FakeService:
    def __init__(
        self, *, freebusy_result=None, freebusy_error=None, insert_result=None, insert_error=None
    ):
        self._freebusy_result = freebusy_result
        self._freebusy_error = freebusy_error
        self._insert_result = insert_result
        self._insert_error = insert_error

    def freebusy(self):
        return SimpleNamespaceQuery(self._freebusy_result, self._freebusy_error)

    def events(self):
        return SimpleNamespaceEvents(self._insert_result, self._insert_error)

    def calendarList(self):
        return SimpleNamespaceCalendarList()


class SimpleNamespaceQuery:
    def __init__(self, result, error):
        self._result = result
        self._error = error

    def query(self, body):
        return _FakeExecutable(self._result, self._error)


class SimpleNamespaceEvents:
    def __init__(self, result, error):
        self._result = result
        self._error = error

    def insert(self, calendarId, body, sendUpdates):
        return _FakeExecutable(self._result, self._error)


class SimpleNamespaceCalendarList:
    def list(self, maxResults):
        return _FakeExecutable({"items": []})


@pytest.fixture(autouse=True)
def _stub_credentials(monkeypatch):
    monkeypatch.setattr(
        "integrations.providers.google_calendar.service_account.Credentials.from_service_account_info",
        lambda info, scopes: object(),
    )


def _patch_build(monkeypatch, service) -> None:
    monkeypatch.setattr("integrations.providers.google_calendar.build", lambda *a, **k: service)


@pytest.fixture
def provider() -> GoogleCalendarProvider:
    return GoogleCalendarProvider()


class TestGetAvailability:
    def test_free_window(self, monkeypatch, provider):
        service = _FakeService(freebusy_result={"calendars": {"primary": {"busy": []}}})
        _patch_build(monkeypatch, service)
        start = datetime(2030, 1, 1, tzinfo=UTC)
        slots = provider.get_availability(
            credentials=CREDENTIALS,
            configuration={},
            window_start=start,
            window_end=start + timedelta(minutes=30),
            timeout_seconds=5,
        )
        assert len(slots) == 1

    def test_busy_window(self, monkeypatch, provider):
        service = _FakeService(
            freebusy_result={"calendars": {"primary": {"busy": [{"start": "x", "end": "y"}]}}}
        )
        _patch_build(monkeypatch, service)
        start = datetime(2030, 1, 1, tzinfo=UTC)
        slots = provider.get_availability(
            credentials=CREDENTIALS,
            configuration={},
            window_start=start,
            window_end=start + timedelta(minutes=30),
            timeout_seconds=5,
        )
        assert slots == []

    def test_malformed_response(self, monkeypatch, provider):
        service = _FakeService(freebusy_result={"unexpected": "shape"})
        _patch_build(monkeypatch, service)
        start = datetime(2030, 1, 1, tzinfo=UTC)
        with pytest.raises(IntegrationMalformedResponseError):
            provider.get_availability(
                credentials=CREDENTIALS,
                configuration={},
                window_start=start,
                window_end=start + timedelta(minutes=30),
                timeout_seconds=5,
            )

    @pytest.mark.parametrize(
        "status,expected",
        [
            (401, IntegrationAuthenticationFailedError),
            (403, IntegrationPermissionDeniedError),
            (429, IntegrationRateLimitedError),
            (500, IntegrationTemporarilyUnavailableError),
            (400, IntegrationInvalidRequestError),
        ],
    )
    def test_http_error_status_mapping(self, monkeypatch, provider, status, expected):
        service = _FakeService(freebusy_error=_http_error(status))
        _patch_build(monkeypatch, service)
        start = datetime(2030, 1, 1, tzinfo=UTC)
        with pytest.raises(expected):
            provider.get_availability(
                credentials=CREDENTIALS,
                configuration={},
                window_start=start,
                window_end=start + timedelta(minutes=30),
                timeout_seconds=5,
            )

    def test_connection_timeout_maps_to_timeout(self, monkeypatch, provider):
        service = _FakeService(freebusy_error=TimeoutError())
        _patch_build(monkeypatch, service)
        start = datetime(2030, 1, 1, tzinfo=UTC)
        from integrations.errors import IntegrationTimeoutError

        with pytest.raises(IntegrationTimeoutError):
            provider.get_availability(
                credentials=CREDENTIALS,
                configuration={},
                window_start=start,
                window_end=start + timedelta(minutes=30),
                timeout_seconds=5,
            )

    def test_naive_datetime_rejected(self, monkeypatch, provider):
        service = _FakeService(freebusy_result={"calendars": {"primary": {"busy": []}}})
        _patch_build(monkeypatch, service)
        start = datetime(2030, 1, 1)
        with pytest.raises(IntegrationInvalidRequestError):
            provider.get_availability(
                credentials=CREDENTIALS,
                configuration={},
                window_start=start,
                window_end=start + timedelta(minutes=30),
                timeout_seconds=5,
            )


class TestCreateBooking:
    def test_success(self, monkeypatch, provider):
        service = _FakeService(insert_result={"id": "evt_1"})
        _patch_build(monkeypatch, service)
        start = datetime(2030, 1, 1, tzinfo=UTC)
        booking = provider.create_booking(
            credentials=CREDENTIALS,
            configuration={},
            start=start,
            end=start + timedelta(minutes=30),
            title="Call",
            attendee_email="a@example.com",
            idempotency_key="k1",
            timeout_seconds=5,
        )
        assert booking.external_event_id == "evt_1"
        assert booking.status == "confirmed"

    def test_conflict_maps_to_slot_unavailable(self, monkeypatch, provider):
        service = _FakeService(insert_error=_http_error(409))
        _patch_build(monkeypatch, service)
        start = datetime(2030, 1, 1, tzinfo=UTC)
        with pytest.raises(CalendarSlotUnavailableError):
            provider.create_booking(
                credentials=CREDENTIALS,
                configuration={},
                start=start,
                end=start + timedelta(minutes=30),
                title="Call",
                attendee_email=None,
                idempotency_key="k1",
                timeout_seconds=5,
            )

    def test_non_conflict_http_error_is_mapped(self, monkeypatch, provider):
        service = _FakeService(insert_error=_http_error(500))
        _patch_build(monkeypatch, service)
        start = datetime(2030, 1, 1, tzinfo=UTC)
        with pytest.raises(IntegrationTemporarilyUnavailableError):
            provider.create_booking(
                credentials=CREDENTIALS,
                configuration={},
                start=start,
                end=start + timedelta(minutes=30),
                title="Call",
                attendee_email=None,
                idempotency_key="k1",
                timeout_seconds=5,
            )

    def test_timeout_during_booking(self, monkeypatch, provider):
        service = _FakeService(insert_error=TimeoutError())
        _patch_build(monkeypatch, service)
        start = datetime(2030, 1, 1, tzinfo=UTC)
        from integrations.errors import IntegrationTimeoutError

        with pytest.raises(IntegrationTimeoutError):
            provider.create_booking(
                credentials=CREDENTIALS,
                configuration={},
                start=start,
                end=start + timedelta(minutes=30),
                title="Call",
                attendee_email=None,
                idempotency_key="k1",
                timeout_seconds=5,
            )

    def test_malformed_response(self, monkeypatch, provider):
        service = _FakeService(insert_result={"unexpected": "shape"})
        _patch_build(monkeypatch, service)
        start = datetime(2030, 1, 1, tzinfo=UTC)
        with pytest.raises(IntegrationMalformedResponseError):
            provider.create_booking(
                credentials=CREDENTIALS,
                configuration={},
                start=start,
                end=start + timedelta(minutes=30),
                title="Call",
                attendee_email=None,
                idempotency_key="k1",
                timeout_seconds=5,
            )


class _FakeServiceWithFailingCalendarList(_FakeService):
    def __init__(self, error):
        super().__init__()
        self._calendar_list_error = error

    def calendarList(self):
        return SimpleNamespaceFailingCalendarList(self._calendar_list_error)


class SimpleNamespaceFailingCalendarList:
    def __init__(self, error):
        self._error = error

    def list(self, maxResults):
        return _FakeExecutable(error=self._error)


class TestProbe:
    def test_probe_success(self, monkeypatch, provider):
        service = _FakeService()
        _patch_build(monkeypatch, service)
        provider.probe(credentials=CREDENTIALS, timeout_seconds=5)

    def test_probe_missing_credentials(self, provider):
        with pytest.raises(IntegrationInvalidRequestError):
            provider.probe(credentials={}, timeout_seconds=5)

    def test_probe_http_error_is_mapped(self, monkeypatch, provider):
        service = _FakeServiceWithFailingCalendarList(_http_error(401))
        _patch_build(monkeypatch, service)
        with pytest.raises(IntegrationAuthenticationFailedError):
            provider.probe(credentials=CREDENTIALS, timeout_seconds=5)

    def test_probe_timeout(self, monkeypatch, provider):
        from integrations.errors import IntegrationTimeoutError

        service = _FakeServiceWithFailingCalendarList(TimeoutError())
        _patch_build(monkeypatch, service)
        with pytest.raises(IntegrationTimeoutError):
            provider.probe(credentials=CREDENTIALS, timeout_seconds=5)
