"""Deterministic character chunker with semantic-friendly boundaries."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from knowledge.errors import ChunkingError
from knowledge.ingestion.extractors import ExtractedSection

CHUNKER_VERSION = "paragraph-char-v1"


@dataclass(frozen=True)
class ChunkDraft:
    ordinal: int
    text: str
    start_offset: int
    end_offset: int
    page_start: int | None = None
    page_end: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)


def _preferred_end(text: str, start: int, maximum: int) -> int:
    if maximum >= len(text):
        return len(text)
    floor = start + max(1, (maximum - start) // 2)
    candidates = [
        text.rfind("\n\n", floor, maximum),
        text.rfind("\n", floor, maximum),
        text.rfind(" ", floor, maximum),
    ]
    boundary = max(candidates)
    return boundary if boundary > start else maximum


def _pages_for_range(
    start: int, end: int, sections: Sequence[ExtractedSection]
) -> tuple[int | None, int | None]:
    pages = [
        section.page_number
        for section in sections
        if section.page_number is not None
        and section.end_offset > start
        and section.start_offset < end
    ]
    return (min(pages), max(pages)) if pages else (None, None)


def chunk_text(
    text: str,
    *,
    chunk_size: int,
    overlap: int,
    minimum_chars: int,
    sections: Sequence[ExtractedSection] = (),
) -> list[ChunkDraft]:
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ChunkingError("Invalid chunk configuration.")
    if not text.strip():
        return []

    drafts: list[ChunkDraft] = []
    cursor = 0
    while cursor < len(text):
        raw_end = min(len(text), cursor + chunk_size)
        end = _preferred_end(text, cursor, raw_end)
        while cursor < end and text[cursor].isspace():
            cursor += 1
        while end > cursor and text[end - 1].isspace():
            end -= 1
        if end <= cursor:
            cursor = raw_end
            continue

        content = text[cursor:end]
        if len(content.strip()) >= minimum_chars or not drafts:
            page_start, page_end = _pages_for_range(cursor, end, sections)
            drafts.append(
                ChunkDraft(
                    ordinal=len(drafts),
                    text=content,
                    start_offset=cursor,
                    end_offset=end,
                    page_start=page_start,
                    page_end=page_end,
                )
            )
        if end >= len(text):
            break
        next_cursor = max(cursor + 1, end - overlap)
        if overlap:
            boundary = text.find(" ", next_cursor, min(end, next_cursor + 80))
            if boundary != -1:
                next_cursor = boundary + 1
        cursor = next_cursor

    if not drafts:
        raise ChunkingError()
    return drafts
