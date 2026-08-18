"""Agent-domain factories with tenant-consistent relationships."""

from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from agents.models import (
    AgentDefinition,
    AgentRun,
    AgentRunStatus,
    AgentStep,
    AgentStepType,
    AgentVersion,
    AgentVersionStatus,
)
from workspaces.tests.factories import WorkspaceFactory


class AgentDefinitionFactory(DjangoModelFactory):
    class Meta:
        model = AgentDefinition

    workspace = factory.SubFactory(WorkspaceFactory)
    name = factory.Sequence(lambda n: f"Support Agent {n}")


class AgentVersionFactory(DjangoModelFactory):
    class Meta:
        model = AgentVersion

    agent_definition = factory.SubFactory(AgentDefinitionFactory)
    version = factory.Sequence(lambda n: n + 1)
    provider = "fake"
    model = "fake-model-1"
    max_model_calls = 1
    max_steps = 20
    wall_time_limit_seconds = 30
    provider_timeout_seconds = 30
    max_retry_attempts = 1


class PublishedAgentVersionFactory(AgentVersionFactory):
    status = AgentVersionStatus.PUBLISHED

    @factory.post_generation
    def _set_published_at(obj, create, extracted, **kwargs):
        from django.utils import timezone

        if create:
            obj.published_at = timezone.now()
            obj.save()


class AgentRunFactory(DjangoModelFactory):
    class Meta:
        model = AgentRun

    agent_version = factory.SubFactory(PublishedAgentVersionFactory)
    workspace = factory.SelfAttribute("agent_version.agent_definition.workspace")
    status = AgentRunStatus.PENDING
    input_message = "How do I reset my password?"


class AgentStepFactory(DjangoModelFactory):
    class Meta:
        model = AgentStep

    run = factory.SubFactory(AgentRunFactory)
    workspace = factory.SelfAttribute("run.workspace")
    sequence = factory.Sequence(lambda n: n + 1)
    step_type = AgentStepType.RUN_STARTED
