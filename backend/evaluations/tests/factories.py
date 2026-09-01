"""Evaluation-domain factories with tenant-consistent relationships."""

from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from agents.tests.factories import PublishedAgentVersionFactory
from workspaces.tests.factories import WorkspaceFactory

from ..models import (
    EvaluationCase,
    EvaluationCaseSnapshot,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
)


class EvaluationDatasetFactory(DjangoModelFactory):
    class Meta:
        model = EvaluationDataset

    workspace = factory.SubFactory(WorkspaceFactory)
    name = factory.Sequence(lambda n: f"Golden set {n}")


class EvaluationCaseFactory(DjangoModelFactory):
    class Meta:
        model = EvaluationCase

    dataset = factory.SubFactory(EvaluationDatasetFactory)
    key = factory.Sequence(lambda n: f"case-{n}")
    name = factory.Sequence(lambda n: f"Case {n}")
    input_message = "Where is my order?"
    seeded_context = factory.LazyFunction(
        lambda: {
            "llm_scenarios": [
                {"response": "It is on the way.", "input_tokens": 10, "output_tokens": 5}
            ]
        }
    )
    expectations = factory.LazyFunction(dict)


class EvaluationRunFactory(DjangoModelFactory):
    class Meta:
        model = EvaluationRun

    dataset = factory.SubFactory(EvaluationDatasetFactory)
    workspace = factory.SelfAttribute("dataset.workspace")
    agent_version = factory.SubFactory(PublishedAgentVersionFactory)
    total_cases = 0


class EvaluationCaseSnapshotFactory(DjangoModelFactory):
    class Meta:
        model = EvaluationCaseSnapshot

    run = factory.SubFactory(EvaluationRunFactory)
    sequence = factory.Sequence(lambda n: n)
    case_key = factory.Sequence(lambda n: f"case-{n}")
    name = "Snapshot case"
    input_message = "Where is my order?"
    seeded_context = factory.LazyFunction(
        lambda: {
            "llm_scenarios": [
                {"response": "It is on the way.", "input_tokens": 10, "output_tokens": 5}
            ]
        }
    )
    expectations = factory.LazyFunction(dict)


class EvaluationResultFactory(DjangoModelFactory):
    class Meta:
        model = EvaluationResult

    run = factory.SelfAttribute("case_snapshot.run")
    case_snapshot = factory.SubFactory(EvaluationCaseSnapshotFactory)
