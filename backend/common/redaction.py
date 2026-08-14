"""Redaction helpers for keeping secrets and sensitive data out of logs/traces.

Used by structured logging and, in later phases, by tool-argument persistence
and observability event capture. Kept dependency-free and side-effect-free so
it is safe to call from any layer.
"""

from __future__ import annotations

from typing import Any

REDACTED = "***REDACTED***"

# Substring match (case-insensitive) against dict keys. Deliberately broad:
# false positives (over-redaction) are safe, false negatives are not.
SENSITIVE_KEY_MARKERS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "access_key",
    "private_key",
    "signing_key",
    "card_number",
    "cvv",
    "ssn",
    "credential",
)


def is_sensitive_key(key: Any) -> bool:
    """Return True if a field name looks like it holds sensitive data."""
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    return any(marker in lowered for marker in SENSITIVE_KEY_MARKERS)


def redact(value: Any, *, extra_keys: frozenset[str] = frozenset()) -> Any:
    """Recursively redact sensitive values within dicts/lists/tuples.

    ``extra_keys`` allows callers (e.g. a specific tool's redaction policy)
    to mark additional exact key names as sensitive without widening the
    global marker list.
    """
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, val in value.items():
            if is_sensitive_key(key) or (isinstance(key, str) and key.lower() in extra_keys):
                redacted[key] = REDACTED
            else:
                redacted[key] = redact(val, extra_keys=extra_keys)
        return redacted
    if isinstance(value, list):
        return [redact(item, extra_keys=extra_keys) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item, extra_keys=extra_keys) for item in value)
    return value
