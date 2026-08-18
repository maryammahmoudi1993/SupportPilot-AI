"""Knowledge-domain factories with tenant-consistent relationships."""

import factory
from factory.django import DjangoModelFactory

from knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentStatus,
    KnowledgeIngestionJob,
    KnowledgeSource,
)
from workspaces.tests.factories import WorkspaceFactory


class KnowledgeSourceFactory(DjangoModelFactory):
    class Meta:
        model = KnowledgeSource

    workspace = factory.SubFactory(WorkspaceFactory)
    name = factory.Sequence(lambda n: f"Knowledge Source {n}")


class KnowledgeDocumentFactory(DjangoModelFactory):
    class Meta:
        model = KnowledgeDocument

    source = factory.SubFactory(KnowledgeSourceFactory)
    workspace = factory.SelfAttribute("source.workspace")
    title = factory.Sequence(lambda n: f"Document {n}")
    original_filename = "policy.txt"
    stored_file = "knowledge/test/policy.txt"
    content_type = "text/plain"
    file_size = 18
    content_sha256 = "a" * 64
    status = KnowledgeDocumentStatus.READY


class KnowledgeIngestionJobFactory(DjangoModelFactory):
    class Meta:
        model = KnowledgeIngestionJob

    document = factory.SubFactory(KnowledgeDocumentFactory)
    workspace = factory.SelfAttribute("document.workspace")
    idempotency_key = factory.Sequence(lambda n: f"job-{n}")


class KnowledgeChunkFactory(DjangoModelFactory):
    class Meta:
        model = KnowledgeChunk

    document = factory.SubFactory(KnowledgeDocumentFactory)
    workspace = factory.SelfAttribute("document.workspace")
    ordinal = factory.Sequence(lambda n: n)
    text = "Duplicate card charges can be refunded after verification."
    start_offset = 0
    end_offset = 58
    embedding = factory.LazyFunction(lambda: [0.0] * 256)
