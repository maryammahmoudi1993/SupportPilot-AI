"""Stable, safe knowledge-domain failures."""


class KnowledgeError(Exception):
    code = "knowledge_ingestion_failed"
    safe_message = "Knowledge ingestion failed."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.safe_message)


class PermanentIngestionError(KnowledgeError):
    """The same input will not succeed when retried."""


class RetryableIngestionError(KnowledgeError):
    code = "knowledge_temporary_failure"
    safe_message = "Knowledge ingestion temporarily failed."


class InvalidFileError(PermanentIngestionError):
    code = "knowledge_invalid_file"
    safe_message = "The uploaded file is invalid."


class EmptyFileError(InvalidFileError):
    code = "knowledge_empty_file"
    safe_message = "The uploaded file is empty."


class FileTooLargeError(InvalidFileError):
    code = "knowledge_file_too_large"
    safe_message = "The uploaded file exceeds the allowed size."


class UnsupportedFileTypeError(InvalidFileError):
    code = "knowledge_unsupported_type"
    safe_message = "The uploaded file type is not supported."


class MalformedPdfError(InvalidFileError):
    code = "knowledge_malformed_pdf"
    safe_message = "The PDF is malformed or unreadable."


class EncryptedPdfError(InvalidFileError):
    code = "knowledge_encrypted_pdf"
    safe_message = "Encrypted or password-protected PDFs are not supported."


class PdfPageLimitError(InvalidFileError):
    code = "knowledge_pdf_page_limit"
    safe_message = "The PDF exceeds the allowed page count."


class NoExtractableTextError(PermanentIngestionError):
    code = "knowledge_no_extractable_text"
    safe_message = "The document contains no usable extractable text."


class ExtractionError(PermanentIngestionError):
    code = "knowledge_extraction_failed"
    safe_message = "The document could not be safely extracted."


class ChunkingError(PermanentIngestionError):
    code = "knowledge_chunking_failed"
    safe_message = "The document could not be divided into usable chunks."


class InvalidEmbeddingError(PermanentIngestionError):
    code = "knowledge_invalid_embedding"
    safe_message = "The embedding provider returned invalid data."


class InvalidRetrievalQueryError(KnowledgeError):
    code = "knowledge_invalid_retrieval_query"
    safe_message = "The retrieval query is invalid."
