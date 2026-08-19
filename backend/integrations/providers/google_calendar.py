"""Google Calendar ``CalendarProvider`` adapter (section 45-52, 134-135).

Service-account (server-configured) credentials only — there is no
per-user OAuth consent/redirect flow yet (section 135: "do not overbuild
it"). Frontend-driven connection onboarding is future work; for Phase 7 an
admin configures a service-account JSON directly as the connection's
credentials.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import google_auth_httplib2
import httplib2
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ..errors import (
    CalendarSlotUnavailableError,
    IntegrationAuthenticationFailedError,
    IntegrationError,
    IntegrationInvalidRequestError,
    IntegrationMalformedResponseError,
    IntegrationPermissionDeniedError,
    IntegrationRateLimitedError,
    IntegrationTemporarilyUnavailableError,
    IntegrationTimeoutError,
)
from .base import AvailabilitySlot, NormalizedBooking

_SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _service(*, credentials: dict, timeout_seconds: float):
    info = credentials.get("service_account_info")
    if not info:
        raise IntegrationInvalidRequestError("No Google service-account credential is configured.")
    creds = service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)
    http = httplib2.Http(timeout=timeout_seconds)
    authed_http = google_auth_httplib2.AuthorizedHttp(creds, http=http)
    return build("calendar", "v3", http=authed_http, cache_discovery=False)


def _map_error(exc: Exception) -> Exception:
    if isinstance(exc, HttpError):
        status = getattr(exc.resp, "status", None)
        if status in (401,):
            return IntegrationAuthenticationFailedError()
        if status in (403,):
            return IntegrationPermissionDeniedError()
        if status == 429:
            return IntegrationRateLimitedError()
        if status is not None and status >= 500:
            return IntegrationTemporarilyUnavailableError()
        return IntegrationInvalidRequestError()
    if isinstance(exc, (TimeoutError, OSError)):
        return IntegrationTimeoutError()
    return IntegrationMalformedResponseError()


def _rfc3339(value: datetime) -> str:
    if value.tzinfo is None:
        raise IntegrationInvalidRequestError("Calendar times must be timezone-aware.")
    return value.isoformat()


class GoogleCalendarProvider:
    """Typed ``CalendarProvider`` backed by the real Google Calendar API."""

    name = "google_calendar"

    def probe(self, *, credentials: dict, timeout_seconds: float) -> None:
        """Read-only connection-test probe: confirms the service account can
        list calendars, without touching any specific calendar's events."""
        try:
            service = _service(credentials=credentials, timeout_seconds=timeout_seconds)
            service.calendarList().list(maxResults=1).execute()
        except HttpError as exc:
            raise _map_error(exc) from exc
        except (TimeoutError, OSError) as exc:
            raise IntegrationTimeoutError() from exc
        except IntegrationError:
            # Already normalized (e.g. by ``_service``'s own credential
            # check) — propagate the specific code as-is rather than
            # collapsing it into the generic catch-all below.
            raise
        except Exception as exc:  # pragma: no cover - defensive, unexpected SDK failure
            raise IntegrationMalformedResponseError() from exc

    def get_availability(
        self,
        *,
        credentials: dict,
        configuration: dict,
        window_start: datetime,
        window_end: datetime,
        timeout_seconds: float,
    ) -> list[AvailabilitySlot]:
        calendar_id = configuration.get("calendar_id", "primary")
        try:
            service = _service(credentials=credentials, timeout_seconds=timeout_seconds)
            response = (
                service.freebusy()
                .query(
                    body={
                        "timeMin": _rfc3339(window_start),
                        "timeMax": _rfc3339(window_end),
                        "items": [{"id": calendar_id}],
                    }
                )
                .execute()
            )
        except HttpError as exc:
            raise _map_error(exc) from exc
        except (TimeoutError, OSError) as exc:
            raise IntegrationTimeoutError() from exc
        except IntegrationError:
            raise
        except Exception as exc:  # pragma: no cover - defensive, unexpected SDK failure
            raise IntegrationMalformedResponseError() from exc

        try:
            busy = response["calendars"][calendar_id]["busy"]
        except (KeyError, TypeError) as exc:
            raise IntegrationMalformedResponseError() from exc
        if busy:
            return []
        return [AvailabilitySlot(start=window_start, end=window_end)]

    def create_booking(
        self,
        *,
        credentials: dict,
        configuration: dict,
        start: datetime,
        end: datetime,
        title: str,
        attendee_email: str | None,
        idempotency_key: str,
        timeout_seconds: float,
    ) -> NormalizedBooking:
        calendar_id = configuration.get("calendar_id", "primary")
        body: dict[str, Any] = {
            "summary": title,
            "start": {"dateTime": _rfc3339(start)},
            "end": {"dateTime": _rfc3339(end)},
            # Google has no native application-idempotency-key concept for
            # events.insert; the stable extended property lets a
            # reconciliation job detect/dedupe if this ever needs replay
            # outside the Phase 6 boundary (section 76 — best-effort provider
            # idempotency where no native primitive exists).
            "extendedProperties": {"private": {"supportpilot_idempotency_key": idempotency_key}},
        }
        if attendee_email:
            body["attendees"] = [{"email": attendee_email}]
        try:
            service = _service(credentials=credentials, timeout_seconds=timeout_seconds)
            event = (
                service.events()
                .insert(calendarId=calendar_id, body=body, sendUpdates="none")
                .execute()
            )
        except HttpError as exc:
            mapped = _map_error(exc)
            status = getattr(exc.resp, "status", None)
            if status == 409:
                raise CalendarSlotUnavailableError() from exc
            raise mapped from exc
        except (TimeoutError, OSError) as exc:
            raise IntegrationTimeoutError() from exc
        except IntegrationError:
            raise
        except Exception as exc:  # pragma: no cover - defensive, unexpected SDK failure
            raise IntegrationMalformedResponseError() from exc

        try:
            event_id = event["id"]
        except (KeyError, TypeError) as exc:
            raise IntegrationMalformedResponseError() from exc
        return NormalizedBooking(
            booking_id=f"bk_{event_id}",
            external_event_id=event_id,
            start=start,
            end=end,
            status="confirmed",
            provider_request_id=event_id,
        )
