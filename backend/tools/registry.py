"""A deterministic, in-process server-side tool registry.

Registration happens explicitly (``register_demo_tools`` called from a
predictable place — see ``tools/apps.py``) rather than via import-time
metaclass/decorator magic, so tests can build an isolated registry, register
exactly the tools a scenario needs, and tear it down without cross-test
contamination (section 15 of the Phase 6 brief).

There is no lookup path that imports a string supplied by a caller or a
model: ``get`` only ever returns an object that was previously handed to
``register`` by trusted, server-side code.
"""

from __future__ import annotations

from .contracts import Tool
from .errors import ToolNotRegisteredError


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.spec.key in self._tools:
            raise ValueError(f"Tool {tool.spec.key!r} is already registered.")
        self._tools[tool.spec.key] = tool

    def get(self, key: str) -> Tool:
        tool = self._tools.get(key)
        if tool is None:
            raise ToolNotRegisteredError(f"Tool {key!r} is not registered.")
        return tool

    def get_or_none(self, key: str) -> Tool | None:
        return self._tools.get(key)

    def list(self) -> list[Tool]:
        return sorted(self._tools.values(), key=lambda tool: tool.spec.key)

    def __contains__(self, key: str) -> bool:
        return key in self._tools

    def reset(self) -> None:
        """Test-only: clear all registrations."""
        self._tools.clear()


registry = ToolRegistry()
