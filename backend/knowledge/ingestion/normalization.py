"""Conservative, offset-stable-enough text normalization."""

import re
import unicodedata

from .extractors import ExtractedDocument, ExtractedSection


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text.replace("\x00", ""))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def normalize_extracted_document(document: ExtractedDocument) -> ExtractedDocument:
    """Normalize per section and rebuild offsets so PDF page citations remain exact."""
    parts: list[str] = []
    sections: list[ExtractedSection] = []
    offset = 0
    for section in document.sections:
        normalized = normalize_text(section.text)
        if not normalized:
            continue
        if parts:
            parts.append("\n\n")
            offset += 2
        start = offset
        parts.append(normalized)
        offset += len(normalized)
        sections.append(
            ExtractedSection(
                text=normalized,
                start_offset=start,
                end_offset=offset,
                page_number=section.page_number,
                title=section.title,
            )
        )
    return ExtractedDocument(
        text="".join(parts), sections=tuple(sections), metadata=document.metadata
    )
