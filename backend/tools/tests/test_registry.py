"""Registry behavior: deterministic lookup, duplicate/unknown rejection,
test isolation (section 73)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from tools.contracts import Tool, ToolSpec
from tools.errors import ToolNotRegisteredError
from tools.registry import ToolRegistry


class _Input(BaseModel):
    value: str


class _Output(BaseModel):
    value: str


def _make_tool(key: str) -> Tool:
    return Tool(
        spec=ToolSpec(
            key=key, display_name=key, description="test", input_model=_Input, output_model=_Output
        ),
        handler=lambda *, context, arguments: _Output(value=arguments.value),
    )


class TestToolRegistry:
    def test_register_and_get(self):
        registry = ToolRegistry()
        tool = _make_tool("test.one")
        registry.register(tool)
        assert registry.get("test.one") is tool

    def test_list_is_sorted_and_deterministic(self):
        registry = ToolRegistry()
        registry.register(_make_tool("b.tool"))
        registry.register(_make_tool("a.tool"))
        assert [t.spec.key for t in registry.list()] == ["a.tool", "b.tool"]

    def test_duplicate_registration_rejected(self):
        registry = ToolRegistry()
        registry.register(_make_tool("dup"))
        with pytest.raises(ValueError):
            registry.register(_make_tool("dup"))

    def test_unknown_tool_raises_stable_error(self):
        registry = ToolRegistry()
        with pytest.raises(ToolNotRegisteredError):
            registry.get("does.not.exist")

    def test_get_or_none(self):
        registry = ToolRegistry()
        assert registry.get_or_none("missing") is None
        tool = _make_tool("present")
        registry.register(tool)
        assert registry.get_or_none("present") is tool

    def test_contains(self):
        registry = ToolRegistry()
        registry.register(_make_tool("present"))
        assert "present" in registry
        assert "missing" not in registry

    def test_reset_clears_all_registrations(self):
        registry = ToolRegistry()
        registry.register(_make_tool("temp"))
        registry.reset()
        assert registry.list() == []

    def test_registries_are_isolated_instances(self):
        a, b = ToolRegistry(), ToolRegistry()
        a.register(_make_tool("only.in.a"))
        assert "only.in.a" not in b


class TestSpecValidation:
    def test_blank_key_rejected(self):
        with pytest.raises(ValueError):
            ToolSpec(
                key="", display_name="x", description="x", input_model=_Input, output_model=_Output
            )

    def test_whitespace_key_rejected(self):
        with pytest.raises(ValueError):
            ToolSpec(
                key=" spaced ",
                display_name="x",
                description="x",
                input_model=_Input,
                output_model=_Output,
            )

    def test_default_timeout_cannot_exceed_max(self):
        with pytest.raises(ValueError):
            ToolSpec(
                key="x",
                display_name="x",
                description="x",
                input_model=_Input,
                output_model=_Output,
                default_timeout_seconds=20,
                max_timeout_seconds=10,
            )

    def test_nonpositive_timeout_rejected(self):
        with pytest.raises(ValueError):
            ToolSpec(
                key="x",
                display_name="x",
                description="x",
                input_model=_Input,
                output_model=_Output,
                default_timeout_seconds=0,
            )


class TestDefaultRegistryDangerousToolsAbsent:
    """Architectural regression test (section 82): the production registry
    must never contain a generic shell/HTTP/SQL/code-execution capability."""

    DANGEROUS_SUBSTRINGS = ("shell", "exec", "eval", "sql", "http", "fetch", "subprocess", "python")

    def test_no_dangerous_tool_keys_registered(self):
        from tools.registry import registry as production_registry

        for tool in production_registry.list():
            lowered = tool.spec.key.lower()
            assert not any(marker in lowered for marker in self.DANGEROUS_SUBSTRINGS), tool.spec.key
