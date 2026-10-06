# syntax=docker/dockerfile:1

FROM python:3.12-slim

# Tesseract is a system binary that pytesseract shells out to; without it the
# API still serves PDF and DOCX but returns 503 for image uploads.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5000

WORKDIR /app

# Dependencies first, so edits to the source do not bust the pip layer cache.
COPY requirements.txt requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY app.py ./
COPY parsers/ parsers/
COPY extractors/ extractors/
COPY utils/ utils/
COPY samples/generate_samples.py samples/

# Run as a non-root user; uploads only ever touch /tmp.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request as u, sys; \
sys.exit(0 if u.urlopen('http://127.0.0.1:5000/health', timeout=4).status == 200 else 1)"

# Two workers handle concurrent uploads; the timeout leaves room for OCR, which
# is the slowest path by far.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "2", \
     "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
