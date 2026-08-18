"""CSRF enforcement for cookie-authenticated mutation endpoints.

DRF's ``APIView`` is CSRF-exempt from Django's ``CsrfViewMiddleware`` by
default; DRF only auto-enforces CSRF for ``SessionAuthentication``. Our
refresh/logout endpoints authenticate via a custom refresh-token cookie, not
a Django session, so they need this explicit check instead. The pattern
mirrors ``rest_framework.authentication.SessionAuthentication.enforce_csrf``.
"""

from __future__ import annotations

from django.middleware.csrf import CsrfViewMiddleware
from rest_framework.exceptions import PermissionDenied


class _CSRFCheck(CsrfViewMiddleware):
    def _reject(self, request, reason):
        # Return the reason instead of raising/responding so the caller can
        # translate it into a DRF exception using the stable error envelope.
        return reason


def enforce_csrf(request) -> None:
    """Raise a 403 PermissionDenied unless the request carries a valid,
    matching CSRF token. Never exposes Django's raw CSRF failure reason
    beyond a short, safe label."""
    # `get_response` and `callback` are never actually invoked by
    # `process_request`/`process_view` below — Django's stubs just don't
    # model that, so the substitutes here are typed loosely on purpose.
    check = _CSRFCheck(lambda r: None)  # type: ignore[arg-type]
    check.process_request(request)
    reason = check.process_view(request, None, (), {})  # type: ignore[arg-type]
    if reason:
        raise PermissionDenied("CSRF validation failed.")
