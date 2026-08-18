"""Knowledge management and idempotent ingestion orchestration."""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from typing import Any, BinaryIO, cast

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from audit.models import AuditAction
from audit.services import record_event
from common.exceptions import ConflictError
from workspaces.models import Workspace

from .errors import (
    KnowledgeError,
    NoExtractableTextError,
    PermanentIngestionError,
    RetryableIngestionError,
)
from .ingestion.chunking import CHUNKER_VERSION, chunk_text
from .ingestion.embeddings import EmbeddingProvider, get_embedding_provider, validate_embeddings
from .ingestion.extractors import get_extractor
from .ingestion.normalization import normalize_extracted_document
from .ingestion.validators import validate_upload
from .models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentStatus,
    KnowledgeIngestionJob,
    KnowledgeIngestionStatus,
    KnowledgeSource,
    KnowledgeSourceType,
)

logger = logging.getLogger("supportpilot")


@dataclass(frozen=True)
class IngestionOutcome:
    job_id: uuid.UUID
    status: str
    chunk_count: int
    already_complete: bool = False


def create_source(
    *, workspace: Workspace, actor: User, data: dict[str, Any], request_id: str | None = None
) -> KnowledgeSource:
    with transaction.atomic():
        source = KnowledgeSource.objects.create(
            workspace=workspace,
            name=data["name"],
            description=data.get("description", ""),
            source_type=data.get("source_type", KnowledgeSourceType.UPLOAD),
            metadata=data.get("metadata", {}),
        )
        record_event(
            action=AuditAction.KNOWLEDGE_SOURCE_CREATED,
            target_type="knowledge_source",
            target_id=source.id,
            actor=actor,
            workspace=workspace,
            metadata={"source_id": str(source.id)},
            request_id=request_id,
        )
    return source


def update_source(
    *,
    workspace: Workspace,
    source: KnowledgeSource,
    actor: User,
    data: dict[str, Any],
    request_id: str | None = None,
) -> KnowledgeSource:
    if source.workspace_id != workspace.id:
        raise ValueError("Source does not belong to workspace.")
    was_active = source.is_active
    with transaction.atomic():
        for field in ("name", "description", "source_type", "metadata", "is_active"):
            if field in data:
                setattr(source, field, data[field])
        source.save()
        action = (
            AuditAction.KNOWLEDGE_SOURCE_DEACTIVATED
            if was_active and not source.is_active
            else AuditAction.KNOWLEDGE_SOURCE_UPDATED
        )
        record_event(
            action=action,
            target_type="knowledge_source",
            target_id=source.id,
            actor=actor,
            workspace=workspace,
            metadata={"source_id": str(source.id)},
            request_id=request_id,
        )
    return source


def _sha256(upload: UploadedFile) -> str:
    digest = hashlib.sha256()
    upload.seek(0)
    for block in upload.chunks():
        digest.update(block)
    upload.seek(0)
    return digest.hexdigest()


def _dispatch_ingestion(job_id: uuid.UUID) -> None:
    from .tasks import ingest_knowledge_document

    ingest_knowledge_document.delay(str(job_id))


def upload_document(
    *,
    workspace: Workspace,
    source: KnowledgeSource,
    actor: User,
    title: str,
    upload: UploadedFile,
    metadata: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> tuple[KnowledgeDocument, KnowledgeIngestionJob]:
    if source.workspace_id != workspace.id or not source.is_active:
        raise ConflictError("The selected knowledge source is not active.")
    validated = validate_upload(upload)
    content_hash = _sha256(upload)
    with transaction.atomic():
        document = KnowledgeDocument.objects.create(
            workspace=workspace,
            source=source,
            uploaded_by=actor,
            title=title.strip() or validated.original_filename,
            original_filename=validated.original_filename,
            stored_file=upload,
            content_type=validated.content_type,
            file_size=validated.size,
            content_sha256=content_hash,
            status=KnowledgeDocumentStatus.QUEUED,
            metadata=metadata or {},
        )
        job = KnowledgeIngestionJob.objects.create(
            workspace=workspace,
            document=document,
            status=KnowledgeIngestionStatus.QUEUED,
            idempotency_key=f"{document.id}:{content_hash}",
        )
        record_event(
            action=AuditAction.KNOWLEDGE_DOCUMENT_UPLOADED,
            target_type="knowledge_document",
            target_id=document.id,
            actor=actor,
            workspace=workspace,
            metadata={"document_id": str(document.id), "source_id": str(source.id)},
            request_id=request_id,
        )
        transaction.on_commit(lambda: _dispatch_ingestion(job.id))
    return document, job


def retry_document(
    *,
    workspace: Workspace,
    document: KnowledgeDocument,
    actor: User,
    request_id: str | None = None,
) -> KnowledgeIngestionJob:
    if document.workspace_id != workspace.id:
        raise ValueError("Document does not belong to workspace.")
    with transaction.atomic():
        locked = KnowledgeDocument.objects.select_for_update().get(pk=document.pk)
        if locked.status != KnowledgeDocumentStatus.FAILED:
            raise ConflictError("Only failed documents can be retried.")
        job = locked.ingestion_jobs.order_by("-created_at").first()
        if job is None:
            raise ConflictError("No ingestion job exists for this document.")
        job.status = KnowledgeIngestionStatus.QUEUED
        job.attempt_count = 0
        job.started_at = None
        job.finished_at = None
        job.error_code = ""
        job.safe_error_message = ""
        job.save()
        locked.status = KnowledgeDocumentStatus.QUEUED
        locked.last_error_code = ""
        locked.last_error_message_safe = ""
        locked.save()
        record_event(
            action=AuditAction.KNOWLEDGE_DOCUMENT_RETRY_REQUESTED,
            target_type="knowledge_document",
            target_id=locked.id,
            actor=actor,
            workspace=workspace,
            metadata={"document_id": str(locked.id), "job_id": str(job.id)},
            request_id=request_id,
        )
        transaction.on_commit(lambda: _dispatch_ingestion(job.id))
    return job


def _mark_failed(job_id: uuid.UUID | str, error: KnowledgeError) -> None:
    with transaction.atomic():
        job = (
            KnowledgeIngestionJob.objects.select_for_update()
            .select_related("document")
            .get(pk=job_id)
        )
        if job.status == KnowledgeIngestionStatus.SUCCEEDED:
            return
        now = timezone.now()
        job.status = KnowledgeIngestionStatus.FAILED
        job.finished_at = now
        job.error_code = error.code
        job.safe_error_message = error.safe_message
        job.save()
        document = job.document
        document.status = KnowledgeDocumentStatus.FAILED
        document.last_error_code = error.code
        document.last_error_message_safe = error.safe_message
        document.save()


def mark_retryable_failure(job_id: uuid.UUID | str, error: RetryableIngestionError) -> None:
    with transaction.atomic():
        job = (
            KnowledgeIngestionJob.objects.select_for_update()
            .select_related("document")
            .get(pk=job_id)
        )
        if job.status == KnowledgeIngestionStatus.SUCCEEDED:
            return
        job.status = KnowledgeIngestionStatus.QUEUED
        job.error_code = error.code
        job.safe_error_message = error.safe_message
        job.save()
        job.document.status = KnowledgeDocumentStatus.QUEUED
        job.document.save()


def fail_ingestion(job_id: uuid.UUID | str, error: KnowledgeError) -> None:
    _mark_failed(job_id, error)


def run_ingestion(
    *, job_id: uuid.UUID | str, provider: EmbeddingProvider | None = None
) -> IngestionOutcome:
    with transaction.atomic():
        job = (
            KnowledgeIngestionJob.objects.select_for_update()
            .select_related("document")
            .get(pk=job_id)
        )
        if job.status == KnowledgeIngestionStatus.SUCCEEDED:
            return IngestionOutcome(job.id, job.status, job.document.chunk_count, True)
        # A redelivery may overlap an active worker or recover a worker that
        # died after claiming the row. Duplicate computation is safe: the
        # final row lock permits exactly one atomic completion.
        job.status = KnowledgeIngestionStatus.PROCESSING
        job.attempt_count += 1
        job.started_at = timezone.now()
        job.finished_at = None
        job.save()
        document = job.document
        document.status = KnowledgeDocumentStatus.PROCESSING
        document.save()

    embedding_provider = provider or get_embedding_provider()
    try:
        with document.stored_file.open("rb") as file_obj:
            extractor = get_extractor(content_type=document.content_type)
            extracted = extractor.extract(cast(BinaryIO, file_obj))
        normalized_document = normalize_extracted_document(extracted)
        normalized = normalized_document.text
        if len(normalized.strip()) < settings.KNOWLEDGE_MIN_CHUNK_CHARS:
            raise NoExtractableTextError()
        drafts = chunk_text(
            normalized,
            chunk_size=settings.KNOWLEDGE_CHUNK_SIZE,
            overlap=settings.KNOWLEDGE_CHUNK_OVERLAP,
            minimum_chars=settings.KNOWLEDGE_MIN_CHUNK_CHARS,
            sections=normalized_document.sections,
        )
        vectors = embedding_provider.embed_documents([draft.text for draft in drafts])
        validated_vectors = validate_embeddings(
            vectors, expected_count=len(drafts), dimension=settings.KNOWLEDGE_EMBEDDING_DIMENSION
        )
    except PermanentIngestionError as exc:
        _mark_failed(job_id, exc)
        return IngestionOutcome(job.id, KnowledgeIngestionStatus.FAILED, 0)
    except (OSError, TimeoutError, ConnectionError) as exc:
        error = RetryableIngestionError()
        mark_retryable_failure(job_id, error)
        raise error from exc
    except Exception as exc:
        logger.exception(
            "knowledge_ingestion_unexpected_failure",
            extra={"document_id": str(document.id), "ingestion_job_id": str(job.id)},
        )
        error = RetryableIngestionError()
        mark_retryable_failure(job_id, error)
        raise error from exc

    with transaction.atomic():
        locked_job = (
            KnowledgeIngestionJob.objects.select_for_update()
            .select_related("document")
            .get(pk=job_id)
        )
        if locked_job.status == KnowledgeIngestionStatus.SUCCEEDED:
            return IngestionOutcome(
                locked_job.id, locked_job.status, locked_job.document.chunk_count, True
            )
        if locked_job.status != KnowledgeIngestionStatus.PROCESSING:
            return IngestionOutcome(
                locked_job.id, locked_job.status, locked_job.document.chunk_count, True
            )
        locked_document = locked_job.document
        KnowledgeChunk.objects.filter(document=locked_document).delete()
        KnowledgeChunk.objects.bulk_create(
            [
                KnowledgeChunk(
                    workspace=locked_document.workspace,
                    document=locked_document,
                    ordinal=draft.ordinal,
                    text=draft.text,
                    start_offset=draft.start_offset,
                    end_offset=draft.end_offset,
                    page_start=draft.page_start,
                    page_end=draft.page_end,
                    metadata=draft.metadata,
                    embedding=vector,
                )
                for draft, vector in zip(drafts, validated_vectors, strict=True)
            ]
        )
        now = timezone.now()
        locked_document.status = KnowledgeDocumentStatus.READY
        locked_document.extracted_char_count = len(normalized)
        locked_document.chunk_count = len(drafts)
        locked_document.last_ingested_at = now
        locked_document.last_error_code = ""
        locked_document.last_error_message_safe = ""
        locked_document.save()
        locked_job.status = KnowledgeIngestionStatus.SUCCEEDED
        locked_job.finished_at = now
        locked_job.error_code = ""
        locked_job.safe_error_message = ""
        locked_job.extractor_version = extractor.version
        locked_job.chunker_version = CHUNKER_VERSION
        locked_job.embedding_provider = embedding_provider.provider_name
        locked_job.embedding_model = embedding_provider.model_name
        locked_job.embedding_dimension = embedding_provider.dimension
        locked_job.save()
    logger.info(
        "knowledge_ingestion_succeeded",
        extra={
            "workspace_id": str(locked_document.workspace_id),
            "document_id": str(locked_document.id),
            "ingestion_job_id": str(locked_job.id),
            "chunk_count": len(drafts),
        },
    )
    return IngestionOutcome(locked_job.id, locked_job.status, len(drafts))


def ingestion_attempt_count(job_id: uuid.UUID | str) -> int:
    return KnowledgeIngestionJob.objects.only("attempt_count").get(pk=job_id).attempt_count
