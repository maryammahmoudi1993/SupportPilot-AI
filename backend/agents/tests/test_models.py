import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from agents.models import (
    AgentRunStatus,
    AgentStep,
    AgentStepType,
    AgentVersionStatus,
)
from workspaces.tests.factories import WorkspaceFactory

from .factories import (
    AgentDefinitionFactory,
    AgentRunFactory,
    AgentStepFactory,
    AgentVersionFactory,
    PublishedAgentVersionFactory,
)


@pytest.mark.django_db
class TestAgentDefinition:
    def test_normalizes_whitespace_and_defaults(self):
        definition = AgentDefinitionFactory(name="  Support   Bot  ")
        assert definition.name == "Support Bot"
        assert str(definition) == "Support Bot"
        assert definition.status == "active"

    def test_blank_name_is_rejected_by_database(self):
        with pytest.raises(IntegrityError):
            AgentDefinitionFactory(name="   ")

    def test_duplicate_name_within_workspace_is_rejected(self):
        workspace = WorkspaceFactory()
        AgentDefinitionFactory(workspace=workspace, name="Same Name")
        with pytest.raises(IntegrityError):
            AgentDefinitionFactory(workspace=workspace, name="Same Name")

    def test_same_name_allowed_across_workspaces(self):
        AgentDefinitionFactory(name="Shared Name")
        # Different workspace (factory default) — must not raise.
        AgentDefinitionFactory(name="Shared Name")


@pytest.mark.django_db
class TestAgentVersion:
    def test_version_uniqueness_within_definition(self):
        definition = AgentDefinitionFactory()
        AgentVersionFactory(agent_definition=definition, version=1)
        with pytest.raises(IntegrityError):
            AgentVersionFactory(agent_definition=definition, version=1)

    def test_same_version_number_allowed_across_definitions(self):
        AgentVersionFactory(version=1)
        AgentVersionFactory(version=1)

    def test_blank_model_fails_validation(self):
        version = AgentVersionFactory.build(model="   ".strip())
        with pytest.raises(ValidationError):
            version.full_clean()

    def test_default_status_is_draft(self):
        version = AgentVersionFactory()
        assert version.status == AgentVersionStatus.DRAFT
        assert version.published_at is None

    def test_published_factory_sets_published_at(self):
        version = PublishedAgentVersionFactory()
        assert version.status == AgentVersionStatus.PUBLISHED
        assert version.published_at is not None

    def test_max_model_calls_must_be_at_least_one(self):
        with pytest.raises(IntegrityError):
            AgentVersionFactory(max_model_calls=0)

    def test_str_representation(self):
        version = AgentVersionFactory(version=3)
        assert str(version) == f"{version.agent_definition_id}:v3"


@pytest.mark.django_db
class TestAgentRun:
    def test_defaults_are_pending_with_zero_usage(self):
        run = AgentRunFactory()
        assert run.status == AgentRunStatus.PENDING
        assert run.model_call_count == 0
        assert run.step_count == 0
        assert run.total_tokens == 0
        assert run.estimated_cost_usd is None

    def test_rejects_agent_version_from_a_different_workspace(self):
        run = AgentRunFactory.build(
            workspace=WorkspaceFactory(), agent_version=PublishedAgentVersionFactory()
        )
        with pytest.raises(ValidationError):
            run.full_clean()

    def test_negative_counters_are_rejected_by_database(self):
        run = AgentRunFactory()
        run.model_call_count = -1
        with pytest.raises(IntegrityError):
            run.save()

    def test_str_representation(self):
        run = AgentRunFactory()
        assert str(run) == f"{run.id}:{run.status}"


@pytest.mark.django_db
class TestAgentStep:
    def test_sequence_uniqueness_within_run(self):
        run = AgentRunFactory()
        AgentStepFactory(run=run, workspace=run.workspace, sequence=1)
        with pytest.raises(IntegrityError):
            AgentStepFactory(run=run, workspace=run.workspace, sequence=1)

    def test_rejects_workspace_mismatch_with_run(self):
        step = AgentStepFactory.build(workspace=WorkspaceFactory(), run=AgentRunFactory())
        with pytest.raises(ValidationError):
            step.full_clean()

    def test_default_step_type_and_status(self):
        step = AgentStepFactory()
        assert step.step_type == AgentStepType.RUN_STARTED
        assert step.status == "succeeded"

    def test_str_representation(self):
        step = AgentStepFactory(sequence=1)
        assert str(step) == f"{step.run_id}#1:{AgentStepType.RUN_STARTED}"

    def test_never_carries_a_chain_of_thought_field(self):
        # Structural guarantee: the model has no field whose name suggests
        # private reasoning storage.
        field_names = {f.name for f in AgentStep._meta.get_fields()}
        forbidden = {"reasoning", "chain_of_thought", "thoughts", "scratchpad", "private_reasoning"}
        assert field_names.isdisjoint(forbidden)
