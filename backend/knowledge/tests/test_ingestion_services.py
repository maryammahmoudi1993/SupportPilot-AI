from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from audit.models import AuditAction, AuditEvent
from common.exceptions import ConflictError
from knowledge.errors import RetryableIngestionError
from knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocumentStatus,
    KnowledgeIngestionStatus,
)
from knowledge.services import (
    create_source,
    retry_document,
    run_ingestion,
    update_source,
    upload_document,
)
from workspaces.tests.factories import WorkspaceMembershipFactory

from .factories import (
    KnowledgeDocumentFactory,
    KnowledgeIngestionJobFactory,
    KnowledgeSourceFactory,
)


def _upload(workspace, source, actor, content=b"Refund duplicate card payment after verification."):
    with patch("knowledge.services._dispatch_ingestion"):
        return upload_document(
            workspace=workspace,
            source=source,
            actor=actor,
            title="Refund policy",
            upload=SimpleUploadedFile("policy.txt", content, content_type="text/plain"),
        )


@pytest.mark.django_db
class TestKnowledgeManagement:
    def test_create_and_deactivate_source_are_audited(self):
        membership = WorkspaceMembershipFactory()
        source = create_source(
            workspace=membership.workspace,
            actor=membership.user,
            data={"name": "  Refund   Guide ", "description": "Rules"},
        )
        assert source.name == "Refund Guide"
        assert AuditEvent.objects.filter(action=AuditAction.KNOWLEDGE_SOURCE_CREATED).exists()
        update_source(
            workspace=membership.workspace,
            source=source,
            actor=membership.user,
            data={"is_active": False},
        )
        assert AuditEvent.objects.filter(action=AuditAction.KNOWLEDGE_SOURCE_DEACTIVATED).exists()

    def test_upload_derives_hash_state_workspace_and_audit(self, tmp_path):
        membership = WorkspaceMembershipFactory()
        source = KnowledgeSourceFactory(workspace=membership.workspace)
        with override_settings(MEDIA_ROOT=tmp_path):
            document, job = _upload(membership.workspace, source, membership.user)
        assert document.workspace == membership.workspace
        assert document.status == KnowledgeDocumentStatus.QUEUED
        assert len(document.content_sha256) == 64
        assert job.status == KnowledgeIngestionStatus.QUEUED
        assert str(membership.workspace.id) in document.stored_file.name
        assert "policy.txt" not in document.stored_file.name
        assert AuditEvent.objects.filter(action=AuditAction.KNOWLEDGE_DOCUMENT_UPLOADED).exists()

    def test_identical_content_is_allowed_across_workspaces(self, tmp_path):
        with override_settings(MEDIA_ROOT=tmp_path):
            hashes = []
            for _ in range(2):
                membership = WorkspaceMembershipFactory()
                source = KnowledgeSourceFactory(workspace=membership.workspace)
                document, _ = _upload(membership.workspace, source, membership.user)
                hashes.append(document.content_sha256)
        assert hashes[0] == hashes[1]

    def test_inactive_source_rejects_upload(self, tmp_path):
        membership = WorkspaceMembershipFactory()
        source = KnowledgeSourceFactory(workspace=membership.workspace, is_active=False)
        with override_settings(MEDIA_ROOT=tmp_path), pytest.raises(ConflictError):
            _upload(membership.workspace, source, membership.user)


@pytest.mark.django_db
class TestIngestionLifecycle:
    @override_settings(
        KNOWLEDGE_CHUNK_SIZE=30, KNOWLEDGE_CHUNK_OVERLAP=5, KNOWLEDGE_MIN_CHUNK_CHARS=5
    )
    def test_complete_ingestion_and_redelivery_are_idempotent(self, tmp_path):
        membership = WorkspaceMembershipFactory()
        source = KnowledgeSourceFactory(workspace=membership.workspace)
        with override_settings(MEDIA_ROOT=tmp_path):
            document, job = _upload(
                membership.workspace,
                source,
                membership.user,
                (
                    b"Refund duplicate payment after verification. "
                    b"Shipping takes several business days."
                ),
            )
            first = run_ingestion(job_id=job.id)
            second = run_ingestion(job_id=job.id)
        document.refresh_from_db()
        job.refresh_from_db()
        assert first.status == KnowledgeIngestionStatus.SUCCEEDED
        assert second.already_complete is True
        assert document.status == KnowledgeDocumentStatus.READY
        assert document.chunk_count == KnowledgeChunk.objects.filter(document=document).count()
        assert job.embedding_dimension == 256
        assert job.attempt_count == 1

    def test_no_text_is_permanent_safe_failure(self, tmp_path):
        membership = WorkspaceMembershipFactory()
        source = KnowledgeSourceFactory(workspace=membership.workspace)
        with override_settings(MEDIA_ROOT=tmp_path):
            document, job = _upload(membership.workspace, source, membership.user, b"   \n  ")
            outcome = run_ingestion(job_id=job.id)
        document.refresh_from_db()
        assert outcome.status == KnowledgeIngestionStatus.FAILED
        assert document.last_error_code == "knowledge_no_extractable_text"
        assert not KnowledgeChunk.objects.filter(document=document).exists()

    def test_processing_redelivery_can_recover_and_still_finalize_once(self, tmp_path):
        membership = WorkspaceMembershipFactory()
        source = KnowledgeSourceFactory(workspace=membership.workspace)
        with override_settings(MEDIA_ROOT=tmp_path):
            document, job = _upload(membership.workspace, source, membership.user)
            job.status = KnowledgeIngestionStatus.PROCESSING
            job.attempt_count = 1
            job.save()
            document.status = KnowledgeDocumentStatus.PROCESSING
            document.save()
            outcome = run_ingestion(job_id=job.id)
        job.refresh_from_db()
        assert outcome.status == KnowledgeIngestionStatus.SUCCEEDED
        assert job.attempt_count == 2
        assert KnowledgeChunk.objects.filter(document=document).count() == 1

    def test_invalid_provider_output_fails_without_partial_chunks(self, tmp_path):
        class BadProvider:
            provider_name = "bad"
            model_name = "bad-v1"
            dimension = 256

            def embed_documents(self, texts):
                return [[0.0]] * len(texts)

            def embed_query(self, text):
                return [0.0]

        membership = WorkspaceMembershipFactory()
        source = KnowledgeSourceFactory(workspace=membership.workspace)
        with override_settings(MEDIA_ROOT=tmp_path):
            document, job = _upload(membership.workspace, source, membership.user)
            outcome = run_ingestion(job_id=job.id, provider=BadProvider())
        document.refresh_from_db()
        assert outcome.status == KnowledgeIngestionStatus.FAILED
        assert document.last_error_code == "knowledge_invalid_embedding"
        assert document.chunk_count == 0

    def test_transient_provider_error_requeues_for_task_retry(self, tmp_path):
        class TemporaryProvider:
            provider_name = "temporary"
            model_name = "temporary-v1"
            dimension = 256

            def embed_documents(self, texts):
                raise TimeoutError("private provider diagnostic")

            def embed_query(self, text):
                raise TimeoutError

        membership = WorkspaceMembershipFactory()
        source = KnowledgeSourceFactory(workspace=membership.workspace)
        with override_settings(MEDIA_ROOT=tmp_path):
            document, job = _upload(membership.workspace, source, membership.user)
            with pytest.raises(RetryableIngestionError):
                run_ingestion(job_id=job.id, provider=TemporaryProvider())
        job.refresh_from_db()
        document.refresh_from_db()
        assert job.status == KnowledgeIngestionStatus.QUEUED
        assert document.status == KnowledgeDocumentStatus.QUEUED
        assert "private" not in job.safe_error_message

    def test_retry_resets_failed_job_and_dispatches(self):
        membership = WorkspaceMembershipFactory()
        document = KnowledgeDocumentFactory(
            workspace=membership.workspace,
            source=KnowledgeSourceFactory(workspace=membership.workspace),
            status=KnowledgeDocumentStatus.FAILED,
        )
        job = KnowledgeIngestionJobFactory(
            workspace=membership.workspace,
            document=document,
            status=KnowledgeIngestionStatus.FAILED,
            attempt_count=3,
            error_code="knowledge_no_extractable_text",
        )
        with patch("knowledge.services._dispatch_ingestion"):
            result = retry_document(
                workspace=membership.workspace, document=document, actor=membership.user
            )
        result.refresh_from_db()
        assert result.id == job.id
        assert result.status == KnowledgeIngestionStatus.QUEUED
        assert result.attempt_count == 0

    def test_ready_document_cannot_be_retried(self):
        membership = WorkspaceMembershipFactory()
        document = KnowledgeDocumentFactory(
            workspace=membership.workspace,
            source=KnowledgeSourceFactory(workspace=membership.workspace),
            status=KnowledgeDocumentStatus.READY,
        )
        with pytest.raises(ConflictError):
            retry_document(workspace=membership.workspace, document=document, actor=membership.user)
