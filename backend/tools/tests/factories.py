"""Tool-domain factories with tenant-consistent relationships."""

from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from agents.tests.factories import AgentRunFactory, PublishedAgentVersionFactory
from tools.models import ToolBinding, ToolDefinition, ToolExecution, ToolExecutionStatus


class ToolDefinitionFactory(DjangoModelFactory):
    class Meta:
        model = ToolDefinition
        django_get_or_create = ("key",)

    key = "demo.echo"
    display_name = "Echo"
    description = "Deterministically echoes back the provided message."
    handler_key = "demo.echo"
    default_timeout_seconds = 5
    max_timeout_seconds = 10


class ToolBindingFactory(DjangoModelFactory):
    class Meta:
        model = ToolBinding

    agent_version = factory.SubFactory(PublishedAgentVersionFactory)
    tool_definition = factory.SubFactory(ToolDefinitionFactory)
    enabled = True


class ToolExecutionFactory(DjangoModelFactory):
    class Meta:
        model = ToolExecution

    agent_run = factory.SubFactory(AgentRunFactory)
    workspace = factory.SelfAttribute("agent_run.workspace")
    agent_version = factory.SelfAttribute("agent_run.agent_version")
    tool_definition = factory.SubFactory(ToolDefinitionFactory)
    tool_binding = factory.SubFactory(
        ToolBindingFactory,
        agent_version=factory.SelfAttribute("..agent_version"),
        tool_definition=factory.SelfAttribute("..tool_definition"),
    )
    status = ToolExecutionStatus.PENDING
    timeout_seconds = 5
