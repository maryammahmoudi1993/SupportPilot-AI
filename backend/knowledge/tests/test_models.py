import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from knowledge.models import KnowledgeDocumentStatus, KnowledgeSource, KnowledgeSourceType
from workspaces.tests.factories import WorkspaceFactory

from .factories import (
    KnowledgeChunkFactory,
    KnowledgeDocumentFactory,
    KnowledgeIngestionJobFactory,
    KnowledgeSourceFactory,
)


@pytest.mark.django_db
class TestKnowledgeSource:
    def test_defaults_normalization_and_string(self):
        source = KnowledgeSourceFactory(name="  Refund   Policies  ")
        assert source.name == "Refund Policies"
        assert str(source) == "Refund Policies"
        assert source.source_type == KnowledgeSourceType.UPLOAD
        assert source.is_active is True

    def test_invalid_source_type_fails_validation(self):
        source = KnowledgeSource(workspace=WorkspaceFactory(), name="Test", source_type="not-real")
        with pytest.raises(ValidationError):
            source.full_clean()

    def test_blank_normalized_name_is_rejected_by_database(self):
        with pytest.raises(IntegrityError):
            KnowledgeSourceFactory(name="   ")


@pytest.mark.django_db
class TestKnowledgeTenantInvariants:
    def test_document_rejects_foreign_source(self):
        document = KnowledgeDocumentFactory.build(
            workspace=WorkspaceFactory(), source=KnowledgeSourceFactory()
        )
        with pytest.raises(ValidationError):
            document.full_clean()

    def test_job_rejects_foreign_document(self):
        job = KnowledgeIngestionJobFactory.build(
            workspace=WorkspaceFactory(), document=KnowledgeDocumentFactory()
        )
        with pytest.raises(ValidationError):
            job.full_clean()

    def test_chunk_rejects_foreign_document(self):
        chunk = KnowledgeChunkFactory.build(
            workspace=WorkspaceFactory(), document=KnowledgeDocumentFactory()
        )
        with pytest.raises(ValidationError):
            chunk.full_clean()

    def test_duplicate_chunk_ordinal_is_rejected(self):
        document = KnowledgeDocumentFactory()
        KnowledgeChunkFactory(document=document, workspace=document.workspace, ordinal=0)
        with pytest.raises(IntegrityError):
            KnowledgeChunkFactory(document=document, workspace=document.workspace, ordinal=0)

    def test_document_status_default_and_safe_fields(self):
        document = KnowledgeDocumentFactory.build(status=KnowledgeDocumentStatus.PENDING)
        assert document.status == KnowledgeDocumentStatus.PENDING
        assert document.last_error_code == ""
        assert document.chunk_count == 0

    def test_job_idempotency_key_is_unique(self):
        KnowledgeIngestionJobFactory(idempotency_key="same")
        with pytest.raises(IntegrityError):
            KnowledgeIngestionJobFactory(idempotency_key="same")
