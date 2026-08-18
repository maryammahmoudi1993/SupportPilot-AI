"""Security validation for untrusted knowledge uploads."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import BinaryIO, cast

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from knowledge.errors import (
    EmptyFileError,
    EncryptedPdfError,
    FileTooLargeError,
    InvalidFileError,
    MalformedPdfError,
    PdfPageLimitError,
    UnsupportedFileTypeError,
)


@dataclass(frozen=True)
class ValidatedUpload:
    original_filename: str
    content_type: str
    size: int


def _safe_filename(name: str) -> str:
    if not name or "\x00" in name:
        raise InvalidFileError()
    normalized = name.replace("\\", "/")
    if PurePath(normalized).name != normalized or normalized in {".", ".."}:
        raise InvalidFileError("Unsafe filename.")
    return normalized


def validate_pdf_stream(file_obj: BinaryIO) -> None:
    position = file_obj.tell()
    try:
        file_obj.seek(0)
        if file_obj.read(5) != b"%PDF-":
            raise MalformedPdfError()
        file_obj.seek(0)
        reader = PdfReader(file_obj, strict=True)
        if reader.is_encrypted:
            raise EncryptedPdfError()
        if len(reader.pages) > settings.KNOWLEDGE_MAX_PDF_PAGES:
            raise PdfPageLimitError()
        # Force page-tree parsing during validation; no page content is executed.
        for page in reader.pages:
            _ = page.mediabox
    except (MalformedPdfError, EncryptedPdfError, PdfPageLimitError):
        raise
    except (PdfReadError, ValueError, TypeError, OSError, EOFError) as exc:
        raise MalformedPdfError() from exc
    finally:
        file_obj.seek(position)


def validate_upload(upload: UploadedFile) -> ValidatedUpload:
    name = _safe_filename(upload.name or "")
    if upload.size is None or upload.size <= 0:
        raise EmptyFileError()
    if upload.size > settings.KNOWLEDGE_MAX_UPLOAD_BYTES:
        raise FileTooLargeError()

    extension = Path(name).suffix.lower()
    allowed = settings.KNOWLEDGE_ALLOWED_CONTENT_TYPES
    content_type = (upload.content_type or "").lower().split(";", 1)[0].strip()
    if content_type not in allowed or extension not in allowed[content_type]:
        raise UnsupportedFileTypeError()

    upload.seek(0)
    prefix = upload.read(min(upload.size, 4096))
    upload.seek(0)
    if b"\x00" in prefix and content_type != "application/pdf":
        raise InvalidFileError("Binary content is not accepted as text.")
    if content_type == "application/pdf":
        validate_pdf_stream(cast(BinaryIO, upload))
    elif prefix.startswith(
        (b"%PDF-", b"MZ", b"\x7fELF", b"PK\x03\x04")
    ) or prefix.lstrip().lower().startswith((b"<html", b"<!doctype html", b"<script")):
        raise UnsupportedFileTypeError()

    return ValidatedUpload(original_filename=name, content_type=content_type, size=upload.size)
