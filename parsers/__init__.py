"""File-type specific text extraction.

``parse_file`` is the single entry point used by the Flask layer; it dispatches
on the logical file kind resolved by :mod:`utils.file_handler`.
"""

from utils.errors import UnsupportedFileType
from utils.text_utils import normalize_text

from . import docx_parser, image_parser, pdf_parser

#: logical kind -> module exposing ``extract_text(path) -> str``
PARSERS = {
    "pdf": pdf_parser,
    "docx": docx_parser,
    "image": image_parser,
}


def parse_file(path, kind):
    """Extract normalised plain text from *path* using the parser for *kind*."""
    parser = PARSERS.get(kind)
    if parser is None:
        raise UnsupportedFileType(f"No parser registered for file kind '{kind}'")
    return normalize_text(parser.extract_text(path))


__all__ = ["PARSERS", "parse_file", "pdf_parser", "docx_parser", "image_parser"]
