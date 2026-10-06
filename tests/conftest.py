"""Shared pytest fixtures."""

import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from samples.generate_samples import RESUME_TEXT, generate_all  # noqa: E402

PARSE_URL = "/api/v1/parse-resume"


@pytest.fixture(scope="session", autouse=True)
def samples():
    """Make sure the sample resumes exist before the tests run."""
    generate_all()
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "samples")


@pytest.fixture
def client():
    app = create_app({"TESTING": True})
    with app.test_client() as test_client:
        yield test_client


@pytest.fixture
def upload(client):
    """Post *content* (bytes or a path) to the parse endpoint."""

    def _upload(content, filename, field="file"):
        if isinstance(content, (str, os.PathLike)):
            with open(content, "rb") as handle:
                content = handle.read()
        data = {field: (io.BytesIO(content), filename)}
        return client.post(PARSE_URL, data=data, content_type="multipart/form-data")

    return _upload


@pytest.fixture
def fake_ocr(monkeypatch):
    """Replace Tesseract with a stub so image tests run without it installed."""
    import parsers.image_parser as image_parser

    def _install(text=RESUME_TEXT):
        monkeypatch.setattr(
            image_parser.pytesseract, "image_to_string",
            lambda image, lang=None, config=None: text,
        )

    return _install
