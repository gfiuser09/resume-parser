"""Shared utilities: upload handling, error types and text helpers."""

from .errors import (
    CorruptedFile,
    EmptyFile,
    FileTooLarge,
    NoFileUploaded,
    OCRError,
    OCRNotAvailable,
    ResumeParserError,
    TextExtractionError,
    UnsupportedFileType,
)
from .file_handler import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE,
    SUPPORTED_LABEL,
    SavedUpload,
    get_extension,
    safe_filename,
)

__all__ = [
    "ALLOWED_EXTENSIONS",
    "MAX_FILE_SIZE",
    "SUPPORTED_LABEL",
    "CorruptedFile",
    "EmptyFile",
    "FileTooLarge",
    "NoFileUploaded",
    "OCRError",
    "OCRNotAvailable",
    "ResumeParserError",
    "SavedUpload",
    "TextExtractionError",
    "UnsupportedFileType",
    "get_extension",
    "safe_filename",
]
