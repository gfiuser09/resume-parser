"""Image text extraction via Tesseract OCR.

This module is the only place that knows about Tesseract. Swapping in a
different OCR backend later means changing ``extract_text`` alone.
"""

import logging
import os

from utils.errors import CorruptedFile, OCRError, OCRNotAvailable

try:
    import pytesseract
    from PIL import Image, ImageOps, UnidentifiedImageError
except ImportError:  # pragma: no cover
    pytesseract = None
    Image = None
    ImageOps = None
    UnidentifiedImageError = Exception

logger = logging.getLogger(__name__)

#: Set TESSERACT_CMD when tesseract.exe is not on PATH (common on Windows).
TESSERACT_CMD = os.environ.get("TESSERACT_CMD")
if TESSERACT_CMD and pytesseract is not None:  # pragma: no cover
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

OCR_LANG = os.environ.get("OCR_LANG", "eng")
#: Page segmentation mode 3 = fully automatic page layout analysis.
OCR_CONFIG = os.environ.get("OCR_CONFIG", "--oem 3 --psm 3")


def _preprocess(image):
    """Light, dependency-free preprocessing that helps Tesseract a lot."""
    image = ImageOps.exif_transpose(image)
    if image.mode not in ("L", "RGB"):
        image = image.convert("RGB")
    image = ImageOps.grayscale(image)
    image = ImageOps.autocontrast(image)

    # Tesseract wants roughly 300 DPI; upscale small screenshots.
    width, height = image.size
    if max(width, height) < 1600:
        scale = min(3.0, 1600 / max(width, height))
        image = image.resize((int(width * scale), int(height * scale)), Image.LANCZOS)
    return image


def extract_text(path):
    """Return the OCR'd text of the image at *path*."""
    if pytesseract is None or Image is None:  # pragma: no cover
        raise OCRError(
            "pytesseract/Pillow are not installed. Run: pip install pytesseract Pillow",
            status_code=503,
        )

    try:
        with Image.open(path) as image:
            image.load()
            prepared = _preprocess(image)
    except UnidentifiedImageError as exc:
        logger.warning("unreadable image: %s", exc)
        raise CorruptedFile(
            "Could not read the image file. It may be corrupted or in an "
            "unsupported format"
        ) from exc
    except OSError as exc:
        logger.warning("corrupted image: %s", exc)
        raise CorruptedFile("The image file appears to be corrupted") from exc

    try:
        text = pytesseract.image_to_string(prepared, lang=OCR_LANG, config=OCR_CONFIG)
    except pytesseract.TesseractNotFoundError as exc:
        raise OCRNotAvailable() from exc
    except pytesseract.TesseractError as exc:
        logger.warning("tesseract error: %s", exc)
        raise OCRError("OCR failed while reading the image") from exc
    except Exception as exc:
        logger.exception("unexpected OCR failure")
        raise OCRError("OCR failed unexpectedly while reading the image") from exc

    text = (text or "").strip()
    if not text:
        raise OCRError(
            "OCR could not find any text in the image. Try a sharper, higher "
            "resolution scan"
        )
    return text
