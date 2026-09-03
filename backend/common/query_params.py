"""Shared, safe parsing for list-endpoint filter query parameters (Phase
14, Section 7): a malformed value must fail predictably with the stable
`validation_error` envelope — never a raw ORM/database exception surfacing
as an unhandled 500, and never a silently-empty result set that would let
the caller believe an honestly-applied filter simply matched nothing.
"""

from __future__ import annotations

from uuid import UUID

from rest_framework.exceptions import ValidationError


def parse_uuid_filter(value: str | None, *, param: str) -> UUID | None:
    """Parse an optional UUID-shaped query parameter.

    Returns ``None`` for an absent/blank parameter (no filter requested).
    Raises DRF's ``ValidationError`` — picked up by
    ``common.exceptions.custom_exception_handler`` and rendered as a
    normal 400 ``validation_error`` — for a present-but-malformed value.
    """
    if not value:
        return None
    try:
        return UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise ValidationError({param: "Must be a valid UUID."}) from None
