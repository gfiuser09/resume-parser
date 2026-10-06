"""Flask application exposing the resume parser.

    POST /api/v1/parse-resume    multipart/form-data, field name "file"

The request pipeline is intentionally thin:

    upload -> validate & store in a temp file -> extract text (parsers)
           -> extract fields (extractors) -> JSON -> delete temp file
"""

import logging
import os

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from extractors import DEFAULT_ENGINE, extract_resume_data
from parsers import parse_file
from utils.errors import NoFileUploaded, ResumeParserError
from utils.file_handler import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE,
    SUPPORTED_LABEL,
    SavedUpload,
)

UPLOAD_FIELD = "file"
API_PREFIX = "/api/v1"

logger = logging.getLogger("resume_parser")


def configure_logging(level=None):
    """Attach a log handler once.

    Needed because ``python app.py`` is not the only entry point: under a WSGI
    server such as gunicorn the ``__main__`` block never runs, and without this
    the INFO-level parse logs would be dropped.
    """
    level = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    root.setLevel(level)
    logger.setLevel(level)


def error_response(message, status_code):
    """Build the uniform error payload used by every failure path."""
    return jsonify({"success": False, "error": message}), status_code


def create_app(config=None):
    """Application factory."""
    configure_logging()
    app = Flask(__name__)
    # Reject oversized bodies before they are buffered into memory/disk.
    app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE
    # Keep the documented field order in responses instead of sorting keys.
    app.json.sort_keys = False
    if config:
        app.config.update(config)

    register_routes(app)
    register_error_handlers(app)
    return app


def register_routes(app):

    @app.get("/health")
    def health():
        return jsonify(
            {
                "success": True,
                "status": "ok",
                "engine": DEFAULT_ENGINE,
                "supported_types": sorted(set(ALLOWED_EXTENSIONS)),
                "max_file_size_mb": round(MAX_FILE_SIZE / (1024 * 1024), 2),
            }
        )

    @app.post(f"{API_PREFIX}/parse-resume")
    def parse_resume():
        storage = request.files.get(UPLOAD_FIELD)
        if storage is None:
            # Help the caller spot a wrong field name quickly.
            if request.files:
                sent = ", ".join(sorted(request.files.keys()))
                raise NoFileUploaded(
                    f"No '{UPLOAD_FIELD}' field in the request (received: {sent})"
                )
            raise NoFileUploaded()

        with SavedUpload(storage) as upload:
            logger.info(
                "parsing upload name=%s kind=%s bytes=%s",
                upload.filename, upload.kind, upload.size,
            )
            text = parse_file(upload.path, upload.kind)
            data = extract_resume_data(text)

        return jsonify({"success": True, "data": data})


def register_error_handlers(app):

    @app.errorhandler(ResumeParserError)
    def handle_parser_error(error):
        logger.info("rejected upload: %s", error.message)
        return error_response(error.message, error.status_code)

    @app.errorhandler(RequestEntityTooLarge)
    def handle_too_large(error):
        limit_mb = MAX_FILE_SIZE / (1024 * 1024)
        return error_response(
            f"File is too large. Maximum allowed size is {limit_mb:.0f} MB", 413
        )

    @app.errorhandler(404)
    def handle_not_found(error):
        return error_response("Endpoint not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(error):
        return error_response(
            f"Method not allowed. Use POST {API_PREFIX}/parse-resume", 405
        )

    @app.errorhandler(HTTPException)
    def handle_http_exception(error):
        return error_response(error.description or error.name, error.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        # Never leak a stack trace to the client; log it instead.
        logger.exception("unexpected error while parsing resume")
        return error_response("Internal server error while processing the resume", 500)


app = create_app()


if __name__ == "__main__":
    logger.info("supported file types: %s", SUPPORTED_LABEL)
    app.run(
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", 5000)),
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
    )
