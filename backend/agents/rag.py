"""Bounded orchestration adapter around the Phase 4 retrieval service."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.conf import settings

from accounts.models import User
from knowledge.retrieval.schemas import Citation
from knowledge.retrieval.services import search_knowledge
from workspaces.models import Workspace


@dataclass(frozen=True)
class KnowledgeReference:
    chunk_id: UUID
    document_id: UUID
    document_title: str
    source_id: UUID
    source_name: str
    rank: int
    content: str
    citation: Citation
    truncated: bool = False

    def citation_metadata(self) -> dict[str, object]:
        return {
            "chunk_id": str(self.chunk_id),
            "document_id": str(self.document_id),
            "title": self.document_title,
            "source_id": str(self.source_id),
            "source_name": self.source_name,
            "citation": self.citation.as_dict(),
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class RetrievedKnowledgeContext:
    retrieval_event_id: UUID
    query: str
    references: tuple[KnowledgeReference, ...]
    truncated: bool

    @property
    def character_count(self) -> int:
        return sum(len(reference.content) for reference in self.references)

    @property
    def citations(self) -> tuple[dict[str, object], ...]:
        return tuple(reference.citation_metadata() for reference in self.references)


def retrieve_agent_knowledge(
    *,
    workspace: Workspace,
    query: str,
    actor: User | None = None,
    top_k: int | None = None,
    max_characters: int | None = None,
) -> RetrievedKnowledgeContext:
    """Retrieve through Phase 4, retaining highest-ranked content first."""
    selected_top_k = top_k if top_k is not None else settings.AGENTS_RAG_TOP_K
    selected_max_characters = (
        max_characters if max_characters is not None else settings.AGENTS_RAG_MAX_CHARACTERS
    )
    if selected_max_characters < 1:
        raise ValueError("RAG context character limit must be positive.")
    bounded_query = query.strip()[: settings.KNOWLEDGE_MAX_QUERY_LENGTH]
    result = search_knowledge(
        workspace=workspace,
        query=bounded_query,
        actor=actor,
        top_k=selected_top_k,
    )

    remaining = selected_max_characters
    references: list[KnowledgeReference] = []
    truncated = False
    for item in result.results:
        if remaining <= 0:
            truncated = True
            break
        content = item.text[:remaining]
        item_truncated = len(content) < len(item.text)
        if content:
            citation = item.citation
            if item_truncated:
                citation = Citation(
                    page_start=citation.page_start,
                    page_end=citation.page_end,
                    start_offset=citation.start_offset,
                    end_offset=min(citation.end_offset, citation.start_offset + len(content)),
                    chunk_ordinal=citation.chunk_ordinal,
                )
            references.append(
                KnowledgeReference(
                    chunk_id=item.chunk_id,
                    document_id=item.document_id,
                    document_title=item.document_title,
                    source_id=item.source_id,
                    source_name=item.source_name,
                    rank=item.rank,
                    content=content,
                    citation=citation,
                    truncated=item_truncated,
                )
            )
            remaining -= len(content)
        truncated = truncated or item_truncated
        if item_truncated:
            break
    if len(references) < len(result.results):
        truncated = True
    return RetrievedKnowledgeContext(
        retrieval_event_id=result.event_id,
        query=result.query,
        references=tuple(references),
        truncated=truncated,
    )
