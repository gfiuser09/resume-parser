"""End-to-end tests for the parse-resume endpoint."""

import glob
import os
import tempfile

import pytest

from samples.generate_samples import RESUME_TEXT

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "samples")
EXPECTED_KEYS = ["candidate_name", "email", "skills", "education", "experience"]


def sample(name):
    return os.path.join(SAMPLES, name)


# --- happy paths -----------------------------------------------------------

@pytest.mark.parametrize("filename", ["resume.pdf", "resume.docx"])
def test_parses_text_documents(upload, filename):
    response = upload(sample(filename), filename)
    assert response.status_code == 200

    body = response.get_json()
    assert body["success"] is True
    assert list(body["data"]) == EXPECTED_KEYS

    data = body["data"]
    assert data["candidate_name"] == "John A. Doe"
    assert data["email"] == "john.doe@example.com"
    assert {"Python", "Flask", "Docker", "PostgreSQL"} <= set(data["skills"])
    assert len(data["education"]) == 2
    assert data["education"][0]["degree"] == "B.Tech in Computer Science"
    assert data["education"][0]["institution"] == "XYZ University"
    assert len(data["experience"]) == 2
    assert data["experience"][0]["title"] == "Senior Backend Engineer"
    assert data["experience"][0]["company"] == "Acme Technologies Pvt Ltd"
    assert data["experience"][0]["duration"] == "Jan 2020 - Present"


@pytest.mark.parametrize("filename", ["resume.png", "resume.jpg"])
def test_parses_images_via_ocr(upload, fake_ocr, filename):
    fake_ocr(RESUME_TEXT)
    response = upload(sample(filename), filename)
    assert response.status_code == 200

    data = response.get_json()["data"]
    assert data["candidate_name"] == "John A. Doe"
    assert data["email"] == "john.doe@example.com"
    assert data["experience"]


def test_health_endpoint(client):
    body = client.get("/health").get_json()
    assert body["success"] is True
    assert body["supported_types"] == ["docx", "jpeg", "jpg", "pdf", "png"]


# --- error handling --------------------------------------------------------

def test_no_file_uploaded(client):
    response = client.post("/api/v1/parse-resume", data={},
                           content_type="multipart/form-data")
    assert response.status_code == 400
    assert response.get_json() == {
        "success": False,
        "error": "No file uploaded. Send the resume as multipart/form-data "
                 "in the 'file' field",
    }


def test_wrong_field_name_is_explained(upload):
    response = upload(b"%PDF-1.4", "resume.pdf", field="resume")
    assert response.status_code == 400
    assert "resume" in response.get_json()["error"]


def test_unsupported_file_type(upload):
    response = upload(b"just some text", "notes.txt")
    assert response.status_code == 415
    assert response.get_json()["error"].startswith("Unsupported file type")


def test_empty_file(upload):
    response = upload(b"", "resume.pdf")
    assert response.status_code == 400
    assert response.get_json()["error"] == "Uploaded file is empty"


@pytest.mark.parametrize(
    "payload,filename",
    [
        (b"%PDF-1.4 not really a pdf" * 20, "resume.pdf"),
        (b"PK\x03\x04 not really a docx" * 20, "resume.docx"),
        (b"\x89PNG\r\n\x1a\n broken" * 20, "resume.png"),
    ],
)
def test_corrupted_files(upload, payload, filename):
    response = upload(payload, filename)
    assert response.status_code == 422
    assert response.get_json()["success"] is False


def test_extension_content_mismatch(upload):
    response = upload(sample("resume.pdf"), "resume.png")
    assert response.status_code == 415
    assert "does not match" in response.get_json()["error"]


def test_file_too_large(upload):
    response = upload(b"%PDF-" + b"0" * (11 * 1024 * 1024), "huge.pdf")
    assert response.status_code == 413
    assert "too large" in response.get_json()["error"]


def test_pdf_without_extractable_text(upload):
    import pymupdf

    document = pymupdf.open()
    document.new_page()
    payload = document.tobytes()
    document.close()

    response = upload(payload, "scanned.pdf")
    assert response.status_code == 422
    assert "No selectable text" in response.get_json()["error"]


def test_ocr_returning_nothing(upload, fake_ocr):
    fake_ocr("   \n  ")
    response = upload(sample("resume.png"), "resume.png")
    assert response.status_code == 422
    assert "OCR could not find any text" in response.get_json()["error"]


def test_method_not_allowed(client):
    assert client.get("/api/v1/parse-resume").status_code == 405


def test_unknown_route(client):
    response = client.post("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.get_json() == {"success": False, "error": "Endpoint not found"}


# --- security --------------------------------------------------------------

def test_temporary_files_are_always_deleted(upload, fake_ocr):
    fake_ocr(RESUME_TEXT)
    pattern = os.path.join(tempfile.gettempdir(), "resume_*")
    before = set(glob.glob(pattern))

    for name in ["resume.pdf", "resume.docx", "resume.png", "resume.jpg"]:
        upload(sample(name), name)
    upload(b"%PDF-broken", "bad.pdf")
    upload(b"", "empty.pdf")
    upload(b"text", "bad.txt")

    assert set(glob.glob(pattern)) - before == set()


def test_filename_is_sanitised(upload):
    response = upload(sample("resume.pdf"), "../../etc/passwd.pdf")
    assert response.status_code == 200


def test_errors_do_not_leak_server_paths(upload):
    error = upload(b"%PDF-1.4 broken" * 20, "resume.pdf").get_json()["error"]
    assert tempfile.gettempdir().lower() not in error.lower()
    assert "resume_" not in error
