"""Explicit API contracts; every ingestion-owned field is read-only."""

from django.conf import settings
from rest_framework import serializers

from .models import (
    KnowledgeDocument,
    KnowledgeIngestionJob,
    KnowledgeSource,
    KnowledgeSourceType,
)


class KnowledgeSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeSource
        fields = [
            "id",
            "name",
            "description",
            "source_type",
            "is_active",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class KnowledgeSourceWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True)
    source_type = serializers.ChoiceField(
        choices=KnowledgeSourceType.choices, required=False, default=KnowledgeSourceType.UPLOAD
    )
    is_active = serializers.BooleanField(required=False)
    metadata = serializers.JSONField(required=False)


class KnowledgeDocumentSerializer(serializers.ModelSerializer):
    source_id = serializers.UUIDField(read_only=True)
    source_name = serializers.CharField(source="source.name", read_only=True)

    class Meta:
        model = KnowledgeDocument
        fields = [
            "id",
            "source_id",
            "source_name",
            "title",
            "original_filename",
            "content_type",
            "file_size",
            "status",
            "is_active",
            "extracted_char_count",
            "chunk_count",
            "last_ingested_at",
            "last_error_code",
            "last_error_message_safe",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class KnowledgeDocumentUploadSerializer(serializers.Serializer):
    source_id = serializers.UUIDField()
    title = serializers.CharField(max_length=255)
    file = serializers.FileField()
    metadata = serializers.JSONField(required=False)


class KnowledgeIngestionJobSerializer(serializers.ModelSerializer):
    document_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = KnowledgeIngestionJob
        fields = [
            "id",
            "document_id",
            "status",
            "attempt_count",
            "started_at",
            "finished_at",
            "error_code",
            "safe_error_message",
            "extractor_version",
            "chunker_version",
            "embedding_provider",
            "embedding_model",
            "embedding_dimension",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class KnowledgeDocumentUploadResponseSerializer(serializers.Serializer):
    document = KnowledgeDocumentSerializer()
    ingestion_job = KnowledgeIngestionJobSerializer()


class KnowledgeSearchRequestSerializer(serializers.Serializer):
    query = serializers.CharField(
        max_length=settings.KNOWLEDGE_MAX_QUERY_LENGTH, trim_whitespace=True
    )
    top_k = serializers.IntegerField(required=False, min_value=1)
    minimum_score = serializers.FloatField(required=False, min_value=0.0, max_value=1.0)
    source_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=False
    )
    document_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=False
    )


class CitationSerializer(serializers.Serializer):
    page_start = serializers.IntegerField(allow_null=True)
    page_end = serializers.IntegerField(allow_null=True)
    start_offset = serializers.IntegerField()
    end_offset = serializers.IntegerField()
    chunk_ordinal = serializers.IntegerField()


class KnowledgeSearchHitSerializer(serializers.Serializer):
    chunk_id = serializers.UUIDField()
    document_id = serializers.UUIDField()
    document_title = serializers.CharField()
    source_id = serializers.UUIDField()
    source_name = serializers.CharField()
    rank = serializers.IntegerField()
    score = serializers.FloatField()
    text = serializers.CharField()
    citation = CitationSerializer()


class KnowledgeSearchResponseSerializer(serializers.Serializer):
    event_id = serializers.UUIDField()
    query = serializers.CharField()
    sufficient_context = serializers.BooleanField()
    results = KnowledgeSearchHitSerializer(many=True)
