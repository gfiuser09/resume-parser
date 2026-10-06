"""PDF text extraction using PyMuPDF (fitz)."""

import logging

from utils.errors import CorruptedFile, TextExtractionError

logger = logging.getLogger(__name__)

try:  # PyMuPDF >= 1.24 prefers the "pymupdf" name; "fitz" is the legacy alias.
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    try:
        import fitz
    except ImportError:
        fitz = None


def extract_text(path):
    """Return the plain text of the PDF at *path*.

    Raises :class:`CorruptedFile` if the document cannot be opened and
    :class:`TextExtractionError` if it opens but yields no usable text (for
    example a scanned resume saved as a PDF of images).
    """
    if fitz is None:  # pragma: no cover
        raise TextExtractionError(
            "PyMuPDF is not installed. Run: pip install PyMuPDF", status_code=503
        )

    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        logger.warning("could not read PDF from disk: %s", exc)
        raise CorruptedFile("Could not read the uploaded PDF file") from exc

    try:
        # Opening from a stream avoids leaving a file handle on the temporary
        # upload when the document turns out to be unparseable.
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        # Log the detail; the client message must not leak server paths.
        logger.warning("failed to open PDF: %s", exc)
        raise CorruptedFile(
            "Could not open the PDF file. It may be corrupted, incomplete or "
            "not a valid PDF"
        ) from exc

    try:
        if document.is_encrypted and not document.authenticate(""):
            raise CorruptedFile("PDF is password protected")

        pages = []
        for page in document:
            try:
                pages.append(page.get_text("text"))
            except Exception:
                # Skip an unreadable page rather than failing the whole file.
                continue
    finally:
        document.close()

    text = "\n".join(pages).strip()
    if not text:
        raise TextExtractionError(
            "No selectable text found in the PDF. It may be a scanned document - "
            "export the page as a JPG/PNG so it can be processed with OCR"
        )
    return text
