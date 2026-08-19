"""Deterministic argument canonicalization for idempotency fingerprinting.

Uses ``json.dumps(..., sort_keys=True)`` — never ``pickle``/``repr`` — so the
fingerprint is stable across process restarts and Python versions and never
executes attacker-controlled bytes on deserialization (section 35 of the
Phase 6 brief).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

MAX_IDEMPOTENCY_KEY_LENGTH = 200


def canonicalize_arguments(arguments: dict[str, Any]) -> str:
    return json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)


def fingerprint_arguments(arguments: dict[str, Any]) -> str:
    canonical = canonicalize_arguments(arguments)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
