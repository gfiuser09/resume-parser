"""Upload handling: validation, file-type detection and temporary storage.

Nothing is written to a permanent location. Uploads are streamed into a
private temporary file, processed, and deleted in a ``finally`` block.
"""

import logging
import os
import tempfile
import time

from werkzeug.utils import secure_filename

from .errors import (
    EmptyFile,
    FileTooLarge,
    NoFileUploaded,
    UnsupportedFileType,
)

logger = logging.getLogger(__name__)

try:  # optional, but listed in requirements.txt
    import filetype
except ImportError:  # pragma: no cover - fallback to magic-byte sniffing
    filetype = None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE_BYTES", 10 * 1024 * 1024))  # 10 MB

#: extension -> logical kind consumed by :mod:`parsers`
ALLOWED_EXTENSIONS = {
    "pdf": "pdf",
    "docx": "docx",
    "jpg": "image",
    "jpeg": "image",
    "png": "image",
}

#: MIME types we accept, mapped to the same logical kinds
ALLOWED_MIME_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "image/jpeg": "image",
    "image/png": "image",
}

SUPPORTED_LABEL = "PDF, DOCX, JPG, JPEG, PNG"

#: Temporary-file deletion retry policy (see SavedUpload.cleanup).
CLEANUP_RETRIES = 3
CLEANUP_RETRY_DELAY = 0.05


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_extension(filename):
    """Return the lowercase extension of *filename* without the dot."""
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].strip().lower()


def _sniff_kind(path):
    """Best-effort content based type detection. Returns a kind or ``None``."""
    if filetype is not None:
        guess = filetype.guess(path)
        if guess is not None:
            return ALLOWED_MIME_TYPES.get(guess.mime)
        return None
    return _sniff_kind_fallback(path)


def _sniff_kind_fallback(path):
    """Magic-byte detection used when ``filetype`` is unavailable."""
    with open(path, "rb") as handle:
        header = handle.read(8)
    if header.startswith(b"%PDF-"):
        return "pdf"
    if header.startswith(b"\xff\xd8\xff"):
        return "image"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image"
    if header.startswith(b"PK\x03\x04"):  # any OOXML/zip container
        return "docx"
    return None


def safe_filename(filename):
    """Sanitise a client supplied filename, never returning an empty string."""
    cleaned = secure_filename(filename or "")
    return cleaned or "upload"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class SavedUpload:
    """A validated upload living in a temporary file.

    Use as a context manager so the temporary file is always removed::

        with SavedUpload(request.files["file"]) as upload:
            text = parse_file(upload.path, upload.kind)
    """

    def __init__(self, storage, max_size=None):
        self.max_size = max_size or MAX_FILE_SIZE
        self.filename = safe_filename(getattr(storage, "filename", None))
        self.extension = get_extension(self.filename)
        self.path = None
        self.kind = None
        self.size = 0
        self._validate_and_store(storage)

    # -- internals ---------------------------------------------------------

    def _validate_and_store(self, storage):
        if storage is None or not getattr(storage, "filename", ""):
            raise NoFileUploaded()

        if self.extension not in ALLOWED_EXTENSIONS:
            raise UnsupportedFileType(
                f"Unsupported file type '.{self.extension or 'unknown'}'. "
                f"Allowed types: {SUPPORTED_LABEL}"
            )

        fd, path = tempfile.mkstemp(prefix="resume_", suffix=f".{self.extension}")
        os.close(fd)
        self.path = path

        try:
            storage.save(path)
            self.size = os.path.getsize(path)

            if self.size == 0:
                raise EmptyFile()
            if self.size > self.max_size:
                limit_mb = self.max_size / (1024 * 1024)
                raise FileTooLarge(f"File is too large. Maximum allowed size is {limit_mb:.0f} MB")

            self.kind = self._resolve_kind()
        except Exception:
            self.cleanup()
            raise

    def _resolve_kind(self):
        """Reconcile the extension with the actual file contents."""
        by_extension = ALLOWED_EXTENSIONS[self.extension]
        sniffed = _sniff_kind(self.path)

        if sniffed is None:
            # Unknown signature: trust the (already whitelisted) extension and
            # let the parser raise a corrupted-file error if it cannot read it.
            return by_extension

        if sniffed != by_extension:
            raise UnsupportedFileType(
                "File content does not match its extension "
                f"('.{self.extension}'). Allowed types: {SUPPORTED_LABEL}"
            )
        return sniffed

    # -- lifecycle ---------------------------------------------------------

    def cleanup(self):
        """Delete the temporary file. Safe to call more than once.

        Deletion is retried briefly: on Windows a library that failed to parse
        the file may still be holding a handle for a moment.
        """
        path, self.path = self.path, None
        if not path:
            return
        for attempt in range(CLEANUP_RETRIES):
            try:
                os.remove(path)
                return
            except FileNotFoundError:
                return
            except OSError as exc:
                if attempt == CLEANUP_RETRIES - 1:
                    logger.warning("could not delete temporary file %s: %s", path, exc)
                    return
                time.sleep(CLEANUP_RETRY_DELAY)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.cleanup()
        return False
