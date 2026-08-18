"""ORM-independent retrieval contract consumed by APIs and future agents."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Citation:
    page_start: int | None
    page_end: int | None
    start_offset: int
    end_offset: int
    chunk_ordinal: int

    def as_dict(self) -> dict[str, int | None]:
        return {
            "page_start": self.page_start,
            "page_end": self.page_end,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "chunk_ordinal": self.chunk_ordinal,
        }


@dataclass(frozen=True)
class RetrievedContext:
    chunk_id: UUID
    document_id: UUID
    document_title: str
    source_id: UUID
    source_name: str
    rank: int
    score: float
    text: str
    citation: Citation


@dataclass(frozen=True)
class SearchResult:
    event_id: UUID
    query: str
    results: tuple[RetrievedContext, ...]
    sufficient_context: bool
