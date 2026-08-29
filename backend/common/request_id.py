"""Inbound ``X-Request-ID`` validation (Phase 11 Block 2 remediation).

A single centralized validator (section 7's "one call site" principle) so
every boundary that accepts a caller-supplied request id —
:class:`common.middleware.RequestIdMiddleware` today, any future one
tomorrow — applies the exact same bounded, ASCII-safe policy.

An invalid inbound value is never treated as a business error (the request
is never rejected for it) and never echoed anywhere: not into the response
header, not into logs, not into trace spans, not into the Celery context.
It is silently replaced with a fresh server-generated id, indistinguishable
from a request that sent no header at all.
"""

from __future__ import annotations

import re
import uuid

#: Bounded, fixed allowed character set: ASCII letters, digits, hyphen,
#: underscore, period — enough to carry a UUID4 (the value this server
#: generates itself) or any conventional correlation id an upstream peer
#: already uses, while excluding whitespace, CR/LF/tab, and every other
#: control/Unicode character an attacker could use to inject content into a
#: log line, HTTP response header, or downstream system. ``fullmatch``
#: (not ``match``) is required below so nothing after a valid-looking
#: prefix — a newline, a null byte — can smuggle a rejected value through.
_MAX_LENGTH = 128
_ALLOWED_REQUEST_ID = re.compile(rf"^[A-Za-z0-9._-]{{1,{_MAX_LENGTH}}}$")


def validate_request_id(value: str | None) -> str:
    """Return ``value`` unchanged if it is a safe inbound request id,
    otherwise a fresh server-generated one.

    Never raises and never rejects the business request solely because the
    caller-supplied ``X-Request-ID`` is malformed (section 2 of the Block 2
    remediation brief) — an unsafe value is simply treated the same as no
    value at all.
    """
    if value and _ALLOWED_REQUEST_ID.fullmatch(value):
        return value
    return str(uuid.uuid4())
