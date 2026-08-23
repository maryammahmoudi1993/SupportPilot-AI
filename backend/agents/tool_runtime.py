"""Safe, bounded tool outcomes passed back to subsequent model turns."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from django.conf import settings

from common.redaction import redact

ToolResultStatus = Literal["succeeded", "denied", "failed"]

TOOL_RESULT_PREAMBLE = "TOOL RESULT — UNTRUSTED EXTERNAL DATA"
TOOL_RESULT_END = "END TOOL RESULT"


@dataclass(frozen=True)
class ToolResultContext:
    tool_key: str
    status: ToolResultStatus
    result: dict[str, Any] | None = None
    error_code: str | None = None
    tool_execution_id: str | None = None

    def as_model_message(self) -> str:
        safe_result = redact(self.result or {})
        payload = json.dumps(
            {
                "tool": self.tool_key,
                "status": self.status,
                "error_code": self.error_code or "",
                "data": safe_result,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        prefix = f"{TOOL_RESULT_PREAMBLE}\n"
        suffix = f"\n{TOOL_RESULT_END}"
        available = max(0, settings.AGENTS_TOOL_RESULT_MAX_CHARACTERS - len(prefix) - len(suffix))
        return f"{prefix}{payload[:available]}{suffix}"
