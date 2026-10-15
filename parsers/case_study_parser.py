"""Case-study text extraction.

Unlike :mod:`pdf_parser` (which reads a PDF's selectable text layer), case
studies are routinely scanned documents or flat image exports, so every PDF
page is rendered to an image the same way a photographed page would be.

:func:`extract_page_images` is the pipeline actually used by the API: it
renders each page/image to PNG bytes and hands them to a Groq vision model
for OCR *and* extraction in one call, since local Tesseract OCR is CPU-bound
and unusably slow on CPU-throttled hosts (e.g. Render's free tier - a single
page there took 38-60s against ~2s on normal hardware). ``extract_text`` is
kept for callers that still want plain Tesseract-OCR'd text.
"""

import io
import logging

from utils.errors import CorruptedFile, OCRError, OCRNotAvailable

from .image_parser import OCR_CONFIG, OCR_LANG, OCR_TIMEOUT_SECONDS, _preprocess
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
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover
    pytesseract = None
    Image = None
    ImageOps = None

logger = logging.getLogger(__name__)

#: Render PDF pages at ~200 DPI (72 is the PDF point default) for OCR-grade
#: sharpness without the huge pixmaps full print resolution would produce.
PDF_OCR_ZOOM = 200 / 72

#: Groq's qwen/qwen3.8-27b vision model accepts at most 3 images per request.
#: Case studies are short by form (~700 words across situation/process/
#: results), so a 3-page cap covers virtually every real document.
MAX_PAGE_IMAGES = 3

#: Pages/images are capped to this longest edge before being base64-encoded,
#: to keep request payloads small without hurting OCR legibility.
MAX_IMAGE_DIMENSION = 2000


def _ocr_page_image(image):
    prepared = _preprocess(image)
    try:
        return pytesseract.image_to_string(
            prepared, lang=OCR_LANG, config=OCR_CONFIG, timeout=OCR_TIMEOUT_SECONDS
        )
    except pytesseract.TesseractNotFoundError as exc:
        raise OCRNotAvailable() from exc
    except RuntimeError as exc:
        logger.warning("tesseract timed out after %ss: %s", OCR_TIMEOUT_SECONDS, exc)
        raise OCRError("OCR timed out while reading a page", status_code=504) from exc
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


def _image_to_png_bytes(image):
    """Normalise orientation/mode and cap size, returning PNG bytes."""
    image = ImageOps.exif_transpose(image)
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    width, height = image.size
    longest = max(width, height)
    if longest > MAX_IMAGE_DIMENSION:
        scale = MAX_IMAGE_DIMENSION / longest
        image = image.resize((int(width * scale), int(height * scale)), Image.LANCZOS)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _page_images_from_pdf(path):
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

        total_pages = document.page_count
        if total_pages > MAX_PAGE_IMAGES:
            logger.info(
                "case study PDF has %s pages; only reading the first %s",
                total_pages, MAX_PAGE_IMAGES,
            )

        matrix = fitz.Matrix(PDF_OCR_ZOOM, PDF_OCR_ZOOM)
        images = []
        for page in document[:MAX_PAGE_IMAGES]:
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            pil_image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            images.append(_image_to_png_bytes(pil_image))
    finally:
        document.close()

    if not images:
        raise OCRError("Could not render any pages from the PDF")
    return images


def extract_page_images(path, kind):
    """Return up to :data:`MAX_PAGE_IMAGES` page images as PNG bytes.

    *kind* is ``"pdf"`` or ``"image"``. These feed a vision model directly
    (see :func:`extractors.case_study_extractor.extract_case_study_data_from_images`)
    instead of going through local Tesseract OCR.
    """
    if Image is None or ImageOps is None:  # pragma: no cover
        raise OCRError("Pillow is not installed. Run: pip install Pillow", status_code=503)

    if kind == "image":
        try:
            with Image.open(path) as image:
                image.load()
                return [_image_to_png_bytes(image)]
        except OSError as exc:
            logger.warning("could not read image: %s", exc)
            raise CorruptedFile(
                "Could not read the image file. It may be corrupted or in an "
                "unsupported format"
            ) from exc
    if kind == "pdf":
        return _page_images_from_pdf(path)
    raise OCRError(f"OCR extraction is not supported for file kind '{kind}'", status_code=415)


__all__ = ["extract_text", "extract_page_images", "MAX_PAGE_IMAGES"]
