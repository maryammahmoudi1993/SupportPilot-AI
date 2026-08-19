"""Direct unit coverage for the demo tool handlers and registration helper
(section 29) — independent of the full execution-service pipeline."""

from __future__ import annotations

import pytest

from tools import demo_tools
from tools.errors import ToolExecutionFailedError
from tools.registry import ToolRegistry


class _Ctx:
    tool_execution_id = "unit-test-execution"


class TestDemoHandlers:
    def test_echo_handler_returns_the_message(self):
        result = demo_tools._echo_handler(
            context=_Ctx(), arguments=demo_tools.EchoInput(message="hi there")
        )
        assert result.echoed == "hi there"

    def test_add_handler_sums_the_operands(self):
        result = demo_tools._add_handler(context=_Ctx(), arguments=demo_tools.AddInput(a=2, b=3))
        assert result.sum == 5

    def test_flaky_handler_succeeds_immediately_with_zero_fail_attempts(self):
        ctx = _Ctx()
        ctx.tool_execution_id = "flaky-zero"
        result = demo_tools._flaky_handler(
            context=ctx, arguments=demo_tools.FlakyInput(fail_attempts=0)
        )
        assert result.attempts_before_success == 1

    def test_flaky_handler_raises_on_configured_failures(self):
        ctx = _Ctx()
        ctx.tool_execution_id = "flaky-fail"
        with pytest.raises(ToolExecutionFailedError):
            demo_tools._flaky_handler(context=ctx, arguments=demo_tools.FlakyInput(fail_attempts=1))

    def test_flaky_handler_sleeps_when_configured(self):
        ctx = _Ctx()
        ctx.tool_execution_id = "flaky-sleep"
        result = demo_tools._flaky_handler(
            context=ctx, arguments=demo_tools.FlakyInput(sleep_seconds=0.01)
        )
        assert result.attempts_before_success == 1


class TestRegisterDemoTools:
    def test_registers_all_three_demo_tools(self):
        registry = ToolRegistry()
        demo_tools.register_demo_tools(registry)
        assert {"demo.echo", "demo.add", "demo.flaky"} <= {t.spec.key for t in registry.list()}

    def test_is_safe_to_call_twice(self):
        registry = ToolRegistry()
        demo_tools.register_demo_tools(registry)
        demo_tools.register_demo_tools(registry)  # must not raise on re-registration
        assert len(registry.list()) == 3
