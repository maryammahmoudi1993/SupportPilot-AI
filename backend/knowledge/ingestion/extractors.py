"""Typed, deterministic extraction boundary for supported documents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import BinaryIO, Protocol

from django.conf import settings
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from knowledge.errors import (
    EncryptedPdfError,
    ExtractionError,
    MalformedPdfError,
    PdfPageLimitError,
)


@dataclass(frozen=True)
class ExtractedSection:
    text: str
    start_offset: int
    end_offset: int
    page_number: int | None = None
    title: str | None = None


@dataclass(frozen=True)
class ExtractedDocument:
    text: str
    sections: tuple[ExtractedSection, ...]
    metadata: dict[str, object] = field(default_factory=dict)


class TextExtractor(Protocol):
    version: str

    def supports(self, *, content_type: str) -> bool: ...

    def extract(self, file_obj: BinaryIO) -> ExtractedDocument: ...


class PlainTextExtractor:
    version = "plain-text-v1"
    content_types = frozenset({"text/plain", "text/markdown"})

    def supports(self, *, content_type: str) -> bool:
        return content_type in self.content_types

    def extract(self, file_obj: BinaryIO) -> ExtractedDocument:
        try:
            file_obj.seek(0)
            text = file_obj.read().decode("utf-8-sig", errors="strict")
        except (UnicodeDecodeError, OSError) as exc:
            raise ExtractionError() from exc
        return ExtractedDocument(
            text=text,
            sections=(ExtractedSection(text=text, start_offset=0, end_offset=len(text)),),
            metadata={"format": "text"},
        )


class PdfTextExtractor:
    version = "pypdf-6.15.0-v1"

    def supports(self, *, content_type: str) -> bool:
        return content_type == "application/pdf"

    def extract(self, file_obj: BinaryIO) -> ExtractedDocument:
        try:
            file_obj.seek(0)
            reader = PdfReader(file_obj, strict=True)
            if reader.is_encrypted:
                raise EncryptedPdfError()
            if len(reader.pages) > settings.KNOWLEDGE_MAX_PDF_PAGES:
                raise PdfPageLimitError()
            parts: list[str] = []
            sections: list[ExtractedSection] = []
            offset = 0
            for page_number, page in enumerate(reader.pages, start=1):
                page_text = page.extract_text() or ""
                if parts:
                    parts.append("\n\n")
                    offset += 2
                start = offset
                parts.append(page_text)
                offset += len(page_text)
                sections.append(
                    ExtractedSection(
                        text=page_text,
                        start_offset=start,
                        end_offset=offset,
                        page_number=page_number,
                    )
                )
            return ExtractedDocument(
                text="".join(parts),
                sections=tuple(sections),
                metadata={"page_count": len(reader.pages)},
            )
        except (EncryptedPdfError, PdfPageLimitError):
            raise
        except (PdfReadError, ValueError, TypeError, OSError, EOFError) as exc:
            raise MalformedPdfError() from exc
        except Exception as exc:
            raise ExtractionError() from exc


EXTRACTORS: tuple[TextExtractor, ...] = (PlainTextExtractor(), PdfTextExtractor())


def get_extractor(*, content_type: str) -> TextExtractor:
    for extractor in EXTRACTORS:
        if extractor.supports(content_type=content_type):
            return extractor
    raise ExtractionError("No extractor is registered for this content type.")
