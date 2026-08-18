"""Tenant-owned knowledge, ingestion, vector, and retrieval provenance models."""

from __future__ import annotations

import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from pgvector.django import HnswIndex, VectorField

from common.models import BaseModel


class KnowledgeSourceType(models.TextChoices):
    UPLOAD = "upload", "Upload"
    MANUAL = "manual", "Manual"


class KnowledgeDocumentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    QUEUED = "queued", "Queued"
    PROCESSING = "processing", "Processing"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"


class KnowledgeIngestionStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    PROCESSING = "processing", "Processing"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"


def knowledge_upload_path(instance: KnowledgeDocument, filename: str) -> str:
    """Generate an opaque tenant-scoped storage name; never trust the client path."""
    suffix = Path(filename).suffix.lower()
    return f"knowledge/{instance.workspace_id}/{uuid.uuid4().hex}{suffix}"


class KnowledgeSource(BaseModel):
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="knowledge_sources"
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    source_type = models.CharField(
        max_length=20, choices=KnowledgeSourceType.choices, default=KnowledgeSourceType.UPLOAD
    )
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=~models.Q(name=""), name="know_source_name_not_blank")
        ]
        indexes = [
            models.Index(fields=["workspace", "is_active"], name="know_src_workspace_active_idx"),
            models.Index(
                fields=["workspace", "-created_at"], name="know_src_workspace_created_idx"
            ),
        ]

    def save(self, *args, **kwargs) -> None:
        self.name = " ".join(self.name.split())
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class KnowledgeDocument(BaseModel):
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="knowledge_documents"
    )
    source = models.ForeignKey(KnowledgeSource, on_delete=models.PROTECT, related_name="documents")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="knowledge_documents_uploaded",
    )
    title = models.CharField(max_length=255)
    original_filename = models.CharField(max_length=255)
    stored_file = models.FileField(upload_to=knowledge_upload_path, max_length=500)
    content_type = models.CharField(max_length=100)
    file_size = models.PositiveBigIntegerField()
    content_sha256 = models.CharField(max_length=64)
    status = models.CharField(
        max_length=20,
        choices=KnowledgeDocumentStatus.choices,
        default=KnowledgeDocumentStatus.PENDING,
    )
    is_active = models.BooleanField(default=True)
    extracted_char_count = models.PositiveIntegerField(default=0)
    chunk_count = models.PositiveIntegerField(default=0)
    last_ingested_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=64, blank=True)
    last_error_message_safe = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "status"], name="know_doc_workspace_status_idx"),
            models.Index(fields=["workspace", "source"], name="know_doc_workspace_source_idx"),
            models.Index(
                fields=["workspace", "-created_at"], name="know_doc_workspace_created_idx"
            ),
            models.Index(
                fields=["workspace", "content_sha256"], name="know_doc_workspace_hash_idx"
            ),
        ]

    def clean(self) -> None:
        if self.source_id and self.workspace_id != self.source.workspace_id:
            raise ValidationError({"source": "Source must belong to the document workspace."})

    def __str__(self) -> str:
        return self.title


class KnowledgeIngestionJob(BaseModel):
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="knowledge_ingestion_jobs"
    )
    document = models.ForeignKey(
        KnowledgeDocument, on_delete=models.CASCADE, related_name="ingestion_jobs"
    )
    status = models.CharField(
        max_length=20,
        choices=KnowledgeIngestionStatus.choices,
        default=KnowledgeIngestionStatus.QUEUED,
    )
    attempt_count = models.PositiveIntegerField(default=0)
    idempotency_key = models.CharField(max_length=128, unique=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    safe_error_message = models.CharField(max_length=255, blank=True)
    extractor_version = models.CharField(max_length=64, blank=True)
    chunker_version = models.CharField(max_length=64, blank=True)
    embedding_provider = models.CharField(max_length=64, blank=True)
    embedding_model = models.CharField(max_length=64, blank=True)
    embedding_dimension = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "status"], name="know_job_workspace_status_idx"),
            models.Index(fields=["document", "-created_at"], name="know_job_document_created_idx"),
        ]

    def clean(self) -> None:
        if self.document_id and self.workspace_id != self.document.workspace_id:
            raise ValidationError({"document": "Document must belong to the job workspace."})

    def __str__(self) -> str:
        return f"{self.document_id}:{self.status}"


class KnowledgeChunk(BaseModel):
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="knowledge_chunks"
    )
    document = models.ForeignKey(KnowledgeDocument, on_delete=models.CASCADE, related_name="chunks")
    ordinal = models.PositiveIntegerField()
    text = models.TextField()
    start_offset = models.PositiveIntegerField()
    end_offset = models.PositiveIntegerField()
    page_start = models.PositiveIntegerField(null=True, blank=True)
    page_end = models.PositiveIntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    embedding = VectorField(dimensions=settings.KNOWLEDGE_EMBEDDING_DIMENSION)

    class Meta:
        ordering = ["document_id", "ordinal"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "ordinal"], name="know_chunk_doc_ordinal_uniq"
            )
        ]
        indexes = [
            models.Index(fields=["workspace", "document"], name="know_chunk_workspace_doc_idx"),
            HnswIndex(
                name="know_chunk_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]

    def clean(self) -> None:
        if self.document_id and self.workspace_id != self.document.workspace_id:
            raise ValidationError({"document": "Document must belong to the chunk workspace."})
        if self.end_offset <= self.start_offset:
            raise ValidationError({"end_offset": "End offset must be greater than start offset."})

    def __str__(self) -> str:
        return f"{self.document_id}#{self.ordinal}"


class RetrievalEvent(BaseModel):
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="knowledge_retrieval_events"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="knowledge_retrieval_events",
    )
    query = models.TextField()
    embedding_provider = models.CharField(max_length=64)
    embedding_model = models.CharField(max_length=64)
    top_k = models.PositiveSmallIntegerField()
    minimum_score = models.FloatField(null=True, blank=True)
    result_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "-created_at"], name="know_ret_workspace_created_idx")
        ]


class RetrievalHit(BaseModel):
    event = models.ForeignKey(RetrievalEvent, on_delete=models.CASCADE, related_name="hits")
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="knowledge_retrieval_hits"
    )
    chunk = models.ForeignKey(
        KnowledgeChunk, on_delete=models.PROTECT, related_name="retrieval_hits"
    )
    rank = models.PositiveSmallIntegerField()
    score = models.FloatField()
    citation = models.JSONField(default=dict)

    class Meta:
        ordering = ["rank"]
        constraints = [
            models.UniqueConstraint(fields=["event", "rank"], name="know_hit_event_rank_uniq")
        ]
        indexes = [models.Index(fields=["workspace", "event"], name="know_hit_workspace_event_idx")]

    def clean(self) -> None:
        if self.event_id and self.workspace_id != self.event.workspace_id:
            raise ValidationError({"event": "Event must belong to the hit workspace."})
        if self.chunk_id and self.workspace_id != self.chunk.workspace_id:
            raise ValidationError({"chunk": "Chunk must belong to the hit workspace."})
