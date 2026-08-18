"""Tenant-filtered pgvector retrieval and persisted citation provenance."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from django.conf import settings
from django.db import transaction
from pgvector.django import CosineDistance

from accounts.models import User
from knowledge.errors import InvalidRetrievalQueryError
from knowledge.ingestion.embeddings import (
    EmbeddingProvider,
    get_embedding_provider,
    validate_embeddings,
)
from knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocumentStatus,
    RetrievalEvent,
    RetrievalHit,
)
from knowledge.selectors import document_get_for_workspace_or_404, source_get_for_workspace_or_404
from workspaces.models import Workspace

from .schemas import Citation, RetrievedContext, SearchResult


def search_knowledge(
    *,
    workspace: Workspace,
    query: str,
    actor: User | None = None,
    top_k: int | None = None,
    source_ids: Sequence[UUID | str] | None = None,
    document_ids: Sequence[UUID | str] | None = None,
    minimum_score: float | None = None,
    provider: EmbeddingProvider | None = None,
) -> SearchResult:
    normalized_query = query.strip()
    if not normalized_query or len(normalized_query) > settings.KNOWLEDGE_MAX_QUERY_LENGTH:
        raise InvalidRetrievalQueryError()
    requested_top_k = top_k if top_k is not None else settings.KNOWLEDGE_DEFAULT_TOP_K
    if not 1 <= requested_top_k <= settings.KNOWLEDGE_MAX_TOP_K:
        raise InvalidRetrievalQueryError("top_k is outside the allowed range.")
    if minimum_score is not None and not 0.0 <= minimum_score <= 1.0:
        raise InvalidRetrievalQueryError("minimum_score must be between 0 and 1.")

    resolved_sources = [
        source_get_for_workspace_or_404(workspace=workspace, source_id=source_id)
        for source_id in (source_ids or [])
    ]
    resolved_documents = [
        document_get_for_workspace_or_404(workspace=workspace, document_id=document_id)
        for document_id in (document_ids or [])
    ]
    embedding_provider = provider or get_embedding_provider()
    query_vector = validate_embeddings(
        [embedding_provider.embed_query(normalized_query)],
        expected_count=1,
        dimension=settings.KNOWLEDGE_EMBEDDING_DIMENSION,
    )[0]

    # Workspace and ready/active predicates are part of the SQL query before
    # distance ordering. No global nearest-neighbour result is ever post-filtered.
    queryset = KnowledgeChunk.objects.filter(
        workspace=workspace,
        document__workspace=workspace,
        document__status=KnowledgeDocumentStatus.READY,
        document__is_active=True,
        document__source__is_active=True,
    ).select_related("document", "document__source")
    if resolved_sources:
        queryset = queryset.filter(document__source_id__in=[item.id for item in resolved_sources])
    if resolved_documents:
        queryset = queryset.filter(document_id__in=[item.id for item in resolved_documents])
    ranked = list(
        queryset.annotate(distance=CosineDistance("embedding", query_vector)).order_by(
            "distance", "document_id", "ordinal", "id"
        )[:requested_top_k]
    )

    contexts: list[RetrievedContext] = []
    for chunk in ranked:
        score = max(-1.0, min(1.0, 1.0 - float(chunk.distance)))
        if minimum_score is not None and score < minimum_score:
            continue
        citation = Citation(
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            start_offset=chunk.start_offset,
            end_offset=chunk.end_offset,
            chunk_ordinal=chunk.ordinal,
        )
        contexts.append(
            RetrievedContext(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                document_title=chunk.document.title,
                source_id=chunk.document.source_id,
                source_name=chunk.document.source.name,
                rank=len(contexts) + 1,
                score=score,
                text=chunk.text,
                citation=citation,
            )
        )

    with transaction.atomic():
        event = RetrievalEvent.objects.create(
            workspace=workspace,
            actor=actor,
            query=normalized_query,
            embedding_provider=embedding_provider.provider_name,
            embedding_model=embedding_provider.model_name,
            top_k=requested_top_k,
            minimum_score=minimum_score,
            result_count=len(contexts),
        )
        RetrievalHit.objects.bulk_create(
            [
                RetrievalHit(
                    event=event,
                    workspace=workspace,
                    chunk_id=context.chunk_id,
                    rank=context.rank,
                    score=context.score,
                    citation=context.citation.as_dict(),
                )
                for context in contexts
            ]
        )
    return SearchResult(
        event_id=event.id,
        query=normalized_query,
        results=tuple(contexts),
        sufficient_context=bool(contexts),
    )
