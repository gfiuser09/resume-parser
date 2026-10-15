"""End-to-end tests for the parse-case-study endpoint.

The pipeline renders page images (real PyMuPDF/Pillow rendering - fast and
deterministic, so it isn't stubbed) and sends them to a Groq vision model.
The vision call itself is stubbed by monkeypatching ``chat_json_vision``
where the extractor imported it, so no network access or API key is needed.
"""

import io
import os

import pytest

CASE_STUDY_URL = "/api/v1/parse-case-study"

FAKE_LLM_REPLY = {
    "title": "CSRD gap analysis for a European manufacturer",
    "client_name": "Nordwind Industries",
    "situation": (
        "Before engagement, Nordwind had no structured view of where its sustainability "
        "reporting stood against the incoming CSRD requirements, and leadership was unsure "
        "which disclosures applied to their operations, leaving the company unprepared for "
        "mandatory reporting with no clear ownership of the process across departments."
    ),
    "process": (
        "The team ran a double materiality assessment, mapped every ESRS datapoint against "
        "existing data sources, and interviewed department heads across finance, operations "
        "and HR to locate reporting gaps before the first mandatory cycle began."
    ),
    "results": (
        "Nordwind entered its first CSRD reporting cycle with 92% of mandatory datapoints "
        "already sourced, cut external audit preparation time by three weeks, and avoided "
        "two material compliance gaps that would otherwise have been flagged by their auditor."
    ),
}


def make_pdf(num_pages=1):
    import pymupdf

    document = pymupdf.open()
    for _ in range(num_pages):
        page = document.new_page()
        page.insert_text((72, 72), "placeholder page")
    payload = document.tobytes()
    document.close()
    return payload


def make_png():
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (10, 10), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def post_case_study(client, content, filename, field="file"):
    if isinstance(content, (str, os.PathLike)):
        with open(content, "rb") as handle:
            content = handle.read()
    data = {field: (io.BytesIO(content), filename)}
    return client.post(CASE_STUDY_URL, data=data, content_type="multipart/form-data")


@pytest.fixture
def fake_groq_vision(monkeypatch):
    """Stub the vision LLM call so tests don't need a network connection or API key."""

    def _install(reply=None, capture=None):
        payload = reply if reply is not None else dict(FAKE_LLM_REPLY)

        def _fake_chat_json_vision(system_prompt, user_text, images):
            if capture is not None:
                capture.append((system_prompt, user_text, images))
            return payload

        monkeypatch.setattr(
            "extractors.case_study_extractor.chat_json_vision", _fake_chat_json_vision
        )

    return _install


# --- happy paths -------------------------------------------------------------

def test_parses_pdf_case_study(client, fake_groq_vision):
    fake_groq_vision()

    response = post_case_study(client, make_pdf(), "case-study.pdf")
    assert response.status_code == 200

    body = response.get_json()
    assert body["success"] is True
    data = body["data"]
    assert list(data) == ["title", "client_name", "situation", "process", "results", "word_counts"]
    assert data["title"] == "CSRD gap analysis for a European manufacturer"
    assert data["client_name"] == "Nordwind Industries"
    assert data["word_counts"]["situation"] == len(data["situation"].split())
    assert data["word_counts"]["process"] == len(data["process"].split())
    assert data["word_counts"]["results"] == len(data["results"].split())


def test_multi_page_pdf_sends_one_image_per_page(client, fake_groq_vision):
    captured = []
    fake_groq_vision(capture=captured)

    response = post_case_study(client, make_pdf(num_pages=3), "case-study.pdf")
    assert response.status_code == 200

    _, _, images = captured[0]
    assert len(images) == 3
    assert all(mime == "image/png" for mime, _ in images)


def test_pdf_pages_are_capped_at_three(client, fake_groq_vision):
    captured = []
    fake_groq_vision(capture=captured)

    response = post_case_study(client, make_pdf(num_pages=5), "case-study.pdf")
    assert response.status_code == 200

    _, _, images = captured[0]
    assert len(images) == 3


def test_parses_image_case_study(client, fake_groq_vision):
    fake_groq_vision()

    response = post_case_study(client, make_png(), "case-study.png")
    assert response.status_code == 200
    assert response.get_json()["data"]["client_name"] == "Nordwind Industries"


# --- word-count enforcement --------------------------------------------------

def test_results_are_clamped_to_max_words(client, fake_groq_vision):
    long_reply = dict(FAKE_LLM_REPLY)
    long_reply["results"] = " ".join(["word"] * 250) + "."
    fake_groq_vision(reply=long_reply)

    response = post_case_study(client, make_pdf(), "case-study.pdf")
    data = response.get_json()["data"]
    assert data["word_counts"]["results"] <= 200


# --- error handling -----------------------------------------------------------

def test_no_file_uploaded(client):
    response = client.post(CASE_STUDY_URL, data={}, content_type="multipart/form-data")
    assert response.status_code == 400
    assert response.get_json()["success"] is False


def test_docx_is_rejected(client):
    response = post_case_study(client, b"PK\x03\x04 not really a docx" * 20, "case-study.docx")
    assert response.status_code == 415
    assert "PDF or image" in response.get_json()["error"]


def test_vision_model_returns_unexpected_shape(client, fake_groq_vision):
    fake_groq_vision(reply="not a dict")

    response = post_case_study(client, make_pdf(), "case-study.pdf")
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["title"] == ""
    assert data["word_counts"] == {"situation": 0, "process": 0, "results": 0}


def test_missing_groq_api_key(client, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    import utils.groq_client as groq_client

    monkeypatch.setattr(groq_client, "_client", None)

    response = post_case_study(client, make_pdf(), "case-study.pdf")
    assert response.status_code == 503
    assert "GROQ_API_KEY" in response.get_json()["error"]
