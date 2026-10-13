"""Case-study text extraction - always via OCR.

Unlike :mod:`pdf_parser` (which reads a PDF's selectable text layer), case
studies are routinely scanned documents or flat image exports, so every PDF
page is rendered to an image and OCR'd the same way a photographed page
would be. Plain images reuse :mod:`image_parser` directly.
"""

import logging

from utils.errors import CorruptedFile, OCRError, OCRNotAvailable

from .image_parser import OCR_CONFIG, OCR_LANG, _preprocess
from .image_parser import extract_text as extract_text_from_image

try:  # PyMuPDF >= 1.24 prefers the "pymupdf" name; "fitz" is the legacy alias.
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    try:
        import fitz
    except ImportError:
        fitz = None

try:
    import pytesseract
    from PIL import Image
except ImportError:  # pragma: no cover
    pytesseract = None
    Image = None

logger = logging.getLogger(__name__)

#: Render PDF pages at ~200 DPI (72 is the PDF point default) for OCR-grade
#: sharpness without the huge pixmaps full print resolution would produce.
PDF_OCR_ZOOM = 200 / 72


def _ocr_page_image(image):
    prepared = _preprocess(image)
    try:
        return pytesseract.image_to_string(prepared, lang=OCR_LANG, config=OCR_CONFIG)
    except pytesseract.TesseractNotFoundError as exc:
        raise OCRNotAvailable() from exc
    except pytesseract.TesseractError as exc:
        logger.warning("tesseract error: %s", exc)
        raise OCRError("OCR failed while reading a page") from exc


def _extract_text_from_pdf(path):
    if fitz is None:  # pragma: no cover
        raise OCRError(
            "PyMuPDF is not installed. Run: pip install PyMuPDF", status_code=503
        )

    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        logger.warning("could not read PDF from disk: %s", exc)
        raise CorruptedFile("Could not read the uploaded PDF file") from exc

    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        logger.warning("failed to open PDF: %s", exc)
        raise CorruptedFile(
            "Could not open the PDF file. It may be corrupted, incomplete or "
            "not a valid PDF"
        ) from exc

    try:
        if document.is_encrypted and not document.authenticate(""):
            raise CorruptedFile("PDF is password protected")

        matrix = fitz.Matrix(PDF_OCR_ZOOM, PDF_OCR_ZOOM)
        pages_text = []
        for page_number, page in enumerate(document, start=1):
            try:
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                text = _ocr_page_image(image)
            except (OCRError, OCRNotAvailable):
                raise
            except Exception:
                # Skip an unreadable page rather than failing the whole document.
                logger.exception("failed to OCR page %s", page_number)
                continue
            text = (text or "").strip()
            if text:
                pages_text.append(text)
    finally:
        document.close()

    text = "\n\n".join(pages_text).strip()
    if not text:
        raise OCRError(
            "OCR could not find any text in the PDF. Try a sharper, higher "
            "resolution scan"
        )
    return text


def extract_text(path, kind):
    """Return the OCR'd text of the case-study document at *path*.

    *kind* is ``"pdf"`` or ``"image"`` (the logical kind resolved by
    :mod:`utils.file_handler`). A multi-page PDF has every page OCR'd and the
    results joined with a blank line between pages.
    """
    if pytesseract is None or Image is None:  # pragma: no cover
        raise OCRError(
            "pytesseract/Pillow are not installed. Run: pip install pytesseract Pillow",
            status_code=503,
        )

    if kind == "image":
        return extract_text_from_image(path)
    if kind == "pdf":
        return _extract_text_from_pdf(path)
    raise OCRError(f"OCR extraction is not supported for file kind '{kind}'", status_code=415)


__all__ = ["extract_text"]
