from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from pypdf import PdfWriter

from knowledge.errors import (
    EmptyFileError,
    EncryptedPdfError,
    FileTooLargeError,
    InvalidFileError,
    MalformedPdfError,
    PdfPageLimitError,
    UnsupportedFileTypeError,
)
from knowledge.ingestion.validators import validate_upload


def _pdf(*, pages=1, encrypted=False):
    output = BytesIO()
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=100, height=100)
    if encrypted:
        writer.encrypt("secret")
    writer.write(output)
    return output.getvalue()


def test_accepts_utf8_text_and_markdown():
    for name, mime in [("policy.txt", "text/plain"), ("guide.md", "text/markdown")]:
        result = validate_upload(SimpleUploadedFile(name, b"safe content", content_type=mime))
        assert result.content_type == mime


def test_empty_file_rejected():
    with pytest.raises(EmptyFileError):
        validate_upload(SimpleUploadedFile("empty.txt", b"", content_type="text/plain"))


@override_settings(KNOWLEDGE_MAX_UPLOAD_BYTES=4)
def test_oversized_file_rejected():
    with pytest.raises(FileTooLargeError):
        validate_upload(SimpleUploadedFile("large.txt", b"12345", content_type="text/plain"))


@pytest.mark.parametrize(
    "name,mime,data",
    [
        ("attack.exe", "application/octet-stream", b"MZpayload"),
        ("fake.pdf", "text/plain", b"not pdf"),
        ("fake.txt", "application/pdf", b"plain text"),
        ("page.html", "text/plain", b"<html><script>x</script>"),
        ("archive.txt", "text/plain", b"PK\x03\x04data"),
    ],
)
def test_extension_mime_or_signature_mismatch_rejected(name, mime, data):
    with pytest.raises((UnsupportedFileTypeError, MalformedPdfError)):
        validate_upload(SimpleUploadedFile(name, data, content_type=mime))


def test_binary_null_in_text_rejected():
    with pytest.raises(InvalidFileError):
        validate_upload(SimpleUploadedFile("binary.txt", b"abc\x00def", content_type="text/plain"))


def test_valid_pdf_is_accepted():
    result = validate_upload(
        SimpleUploadedFile("guide.pdf", _pdf(), content_type="application/pdf")
    )
    assert result.content_type == "application/pdf"


def test_malformed_pdf_is_rejected_safely():
    with pytest.raises(MalformedPdfError):
        validate_upload(
            SimpleUploadedFile("bad.pdf", b"%PDF-broken", content_type="application/pdf")
        )


def test_encrypted_pdf_is_rejected():
    with pytest.raises(EncryptedPdfError):
        validate_upload(
            SimpleUploadedFile("locked.pdf", _pdf(encrypted=True), content_type="application/pdf")
        )


@override_settings(KNOWLEDGE_MAX_PDF_PAGES=1)
def test_pdf_page_limit_is_enforced():
    with pytest.raises(PdfPageLimitError):
        validate_upload(
            SimpleUploadedFile("long.pdf", _pdf(pages=2), content_type="application/pdf")
        )
