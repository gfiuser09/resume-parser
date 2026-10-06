# Resume Parser API

A small, modular Flask service that accepts a resume (PDF, DOCX, JPG/JPEG, PNG),
extracts the text, and returns structured candidate information as JSON.

```text
Upload Resume
      |
   Flask API            app.py
      |
 Extract Text           parsers/   (PyMuPDF | python-docx | Tesseract OCR)
      |
Extract Resume Data     extractors/ (rule-based, swappable)
      |
  Return JSON
```

The extraction logic lives behind an `ExtractionEngine` interface, so the
rule-based engine can be replaced with an LLM or a better NLP model without
touching the HTTP layer.

---

## Project structure

```text
resume-parser/
├── app.py                      # Flask app, routing, error handlers
├── requirements.txt
├── requirements-dev.txt        # requirements.txt + pytest
├── README.md
│
├── parsers/                    # file type -> plain text
│   ├── __init__.py             # parse_file() dispatcher
│   ├── pdf_parser.py           # PyMuPDF
│   ├── docx_parser.py          # python-docx (paragraphs + tables)
│   └── image_parser.py         # Pillow preprocessing + Tesseract OCR
│
├── extractors/                 # plain text -> structured data
│   ├── __init__.py             # engine registry, extract_resume_data()
│   ├── resume_extractor.py     # ExtractionEngine, RuleBasedEngine, name/email
│   ├── skills.py
│   ├── education.py
│   └── experience.py
│
├── utils/
│   ├── __init__.py
│   ├── file_handler.py         # validation, type detection, temp files
│   ├── errors.py               # error types -> HTTP status codes
│   └── text_utils.py           # normalisation, section splitting, dates
│
├── samples/
│   └── generate_samples.py     # creates test resumes in every format
├── tests/
│   ├── conftest.py
│   ├── test_api.py
│   └── test_extractors.py
│
├── Dockerfile                  # gunicorn + Tesseract, runs as non-root
├── docker-compose.yml
├── .dockerignore
└── requirements-prod.txt       # requirements.txt + gunicorn
```

`utils/errors.py` and `utils/text_utils.py` are additions to the requested
layout: the first keeps HTTP status mapping out of the parsers, the second
holds text plumbing shared by all three extractors.

---

## Installation

Requires **Python 3.9+**.

```bash
# 1. Clone / enter the project
cd resume-parser

# 2. Create a virtual environment
python -m venv .venv

#    Windows (PowerShell)
.venv\Scripts\Activate.ps1
#    macOS / Linux
source .venv/bin/activate

# 3. Install Python dependencies
pip install -r requirements.txt
```

### Tesseract OCR (only needed for image resumes)

`pytesseract` is a wrapper — the Tesseract binary must be installed separately.
PDF and DOCX parsing work without it.

| Platform | Command |
| --- | --- |
| Windows | `winget install UB-Mannheim.TesseractOCR` or [download the installer](https://github.com/UB-Mannheim/tesseract/wiki) |
| macOS | `brew install tesseract` |
| Debian / Ubuntu | `sudo apt install tesseract-ocr` |
| Fedora | `sudo dnf install tesseract` |

Verify it is on your PATH:

```bash
tesseract --version
```

If it is installed but not on PATH (common on Windows), point the app at it:

```bash
# PowerShell
$env:TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"
# bash
export TESSERACT_CMD=/usr/local/bin/tesseract
```

Without Tesseract, image uploads return a clear `503` rather than crashing.

---

## Running the server

```bash
python app.py
```

The API is then available at `http://localhost:5000`.

```text
POST /api/v1/parse-resume    parse a resume
GET  /health                 engine, limits and supported types
```

Configuration (all optional, read from the environment):

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `5000` | Port to bind |
| `HOST` | `0.0.0.0` | Interface to bind |
| `FLASK_DEBUG` | `0` | Set to `1` for the reloader/debugger |
| `MAX_FILE_SIZE_BYTES` | `10485760` (10 MB) | Upload size limit |
| `TESSERACT_CMD` | – | Full path to `tesseract` if not on PATH |
| `OCR_LANG` | `eng` | Tesseract language pack(s), e.g. `eng+deu` |
| `EXTRACTION_ENGINE` | `rule-based` | Which registered engine to use |
| `LOG_LEVEL` | `INFO` | Logging level |

For production, run it behind a WSGI server instead of the dev server:

```bash
pip install gunicorn
gunicorn --bind 0.0.0.0:5000 --workers 4 "app:app"
```

---

## Running with Docker

The image installs Tesseract, so **image resumes work out of the box** - no
local OCR setup needed. It runs under gunicorn as a non-root user.

### Build and run

```bash
docker build -t resume-parser:latest .
docker run --rm -p 5000:5000 --name resume-parser resume-parser:latest
```

### Or with Compose

```bash
docker compose up --build        # add -d to run detached
docker compose logs -f
docker compose down
```

If port 5000 is already taken (e.g. a local `python app.py` is running), pick
another host port:

```bash
HOST_PORT=8080 docker compose up --build
```

The Compose service runs with a read-only root filesystem plus a `tmpfs` at
`/tmp` (the only place uploads are ever written) and `no-new-privileges`.

### Test the container

```bash
curl http://localhost:5000/health

curl -X POST http://localhost:5000/api/v1/parse-resume -F "file=@samples/resume.pdf"
curl -X POST http://localhost:5000/api/v1/parse-resume -F "file=@samples/resume.docx"
curl -X POST http://localhost:5000/api/v1/parse-resume -F "file=@samples/resume.png"
```

If you have no sample files yet, generate them on the host with
`python samples/generate_samples.py`, or inside the container:

```bash
docker exec resume-parser python samples/generate_samples.py
docker exec resume-parser ls samples/
```

### Configuration

Pass the same environment variables as the local server:

```bash
docker run --rm -p 8080:5000   -e MAX_FILE_SIZE_BYTES=20971520   -e LOG_LEVEL=DEBUG   resume-parser:latest
```

`TESSERACT_CMD` is not needed - the binary is on the PATH inside the image.

### Extra OCR languages

Only English is installed. To add more, extend the `apt-get install` line in the
[Dockerfile](Dockerfile), e.g. `tesseract-ocr-hin tesseract-ocr-deu`, then set
`OCR_LANG=eng+hin`.

### Notes

- `docker build` uses [.dockerignore](.dockerignore), which keeps `.git`,
  `tests/`, caches and any generated sample files out of the build context.
- `requirements-prod.txt` is `requirements.txt` plus gunicorn, so the local
  install stays exactly as specified.
- Tune workers for your host: `--workers` roughly `2 x CPU + 1`. OCR is
  CPU-bound, so more workers than cores will not help.
- Scanned-image requests take seconds, not milliseconds; the gunicorn timeout is
  set to 120s to accommodate them.

---

## Example request

```bash
curl -X POST http://localhost:5000/api/v1/parse-resume \
  -F "file=@resume.pdf"
```

On Windows PowerShell, use `curl.exe` so it is not aliased to `Invoke-WebRequest`:

```powershell
curl.exe -X POST http://localhost:5000/api/v1/parse-resume -F "file=@resume.pdf"
```

## Example response

`200 OK`

```json
{
  "success": true,
  "data": {
    "candidate_name": "John A. Doe",
    "email": "john.doe@example.com",
    "skills": [
      "Django", "Docker", "Flask", "Git", "Go", "JavaScript", "Kubernetes",
      "PostgreSQL", "Python", "React", "Redis", "REST APIs", "SQL"
    ],
    "education": [
      {
        "degree": "B.Tech in Computer Science",
        "institution": "XYZ University",
        "year": "2013 - 2017",
        "details": "CGPA: 8.7/10"
      },
      {
        "degree": "Higher Secondary",
        "institution": "ABC Public School",
        "year": "2013",
        "details": "Percentage: 92%"
      }
    ],
    "experience": [
      {
        "title": "Senior Backend Engineer",
        "company": "Acme Technologies Pvt Ltd",
        "duration": "Jan 2020 - Present",
        "location": "",
        "description": "Designed REST APIs serving 2M requests/day using Flask and PostgreSQL. Led a team of 4 engineers and reduced p95 latency by 40%."
      },
      {
        "title": "Software Engineer",
        "company": "Globex Solutions",
        "duration": "Jun 2017 - Dec 2019",
        "location": "Bangalore",
        "description": "Built internal tooling in Python and automated deployments with Docker."
      }
    ]
  }
}
```

Fields that cannot be found come back empty (`""` / `[]`) rather than missing,
so the response shape is always the same.

---

## Error responses

Every failure returns the same shape:

```json
{
  "success": false,
  "error": "Unsupported file type"
}
```

| Situation | Status | Example message |
| --- | --- | --- |
| No file uploaded / wrong field name | `400` | `No file uploaded. Send the resume as multipart/form-data in the 'file' field` |
| Empty file | `400` | `Uploaded file is empty` |
| Endpoint not found | `404` | `Endpoint not found` |
| Wrong HTTP method | `405` | `Method not allowed. Use POST /api/v1/parse-resume` |
| File too large | `413` | `File is too large. Maximum allowed size is 10 MB` |
| Unsupported type, or extension/content mismatch | `415` | `Unsupported file type '.txt'. Allowed types: PDF, DOCX, JPG, JPEG, PNG` |
| Corrupted / unreadable file | `422` | `Could not open the PDF file. It may be corrupted, incomplete or not a valid PDF` |
| No extractable text (e.g. scanned PDF) | `422` | `No selectable text found in the PDF...` |
| OCR found no text | `422` | `OCR could not find any text in the image...` |
| Tesseract not installed | `503` | `OCR engine (Tesseract) is not installed or not on PATH...` |
| Unexpected server error | `500` | `Internal server error while processing the resume` |

Internal details (library messages, file paths) are logged server-side and never
returned to the client.

---

## Testing locally

### 1. Generate sample resumes

Creates `resume.pdf`, `resume.docx`, `resume.png`, `resume.jpg` and
`resume.txt` in `samples/`:

```bash
python samples/generate_samples.py
```

### 2. Start the server in one terminal

```bash
python app.py
```

### 3. Send each format from another terminal

```bash
# PDF
curl -X POST http://localhost:5000/api/v1/parse-resume -F "file=@samples/resume.pdf"

# DOCX
curl -X POST http://localhost:5000/api/v1/parse-resume -F "file=@samples/resume.docx"

# PNG (requires Tesseract)
curl -X POST http://localhost:5000/api/v1/parse-resume -F "file=@samples/resume.png"

# JPG (requires Tesseract)
curl -X POST http://localhost:5000/api/v1/parse-resume -F "file=@samples/resume.jpg"
```

Pipe through `python -m json.tool` for readable output:

```bash
curl -s -X POST http://localhost:5000/api/v1/parse-resume \
  -F "file=@samples/resume.pdf" | python -m json.tool
```

### 4. Check the error paths

```bash
# no file
curl -X POST http://localhost:5000/api/v1/parse-resume

# unsupported type
echo "hello" > note.txt
curl -X POST http://localhost:5000/api/v1/parse-resume -F "file=@note.txt"

# health check
curl http://localhost:5000/health
```

### 5. Run the automated test suite

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

62 tests cover both the HTTP layer (every status code above, plus temp-file
cleanup) and the extraction rules. The image tests stub out Tesseract, so the
whole suite passes without it installed.

Testing your own resume:

```bash
curl -X POST http://localhost:5000/api/v1/parse-resume -F "file=@/path/to/your_resume.pdf"
```

---

## Security

- **Size limit** — enforced twice: `MAX_CONTENT_LENGTH` rejects oversized
  request bodies before buffering, and `SavedUpload` re-checks the file on disk.
- **Type allow-list** — only `.pdf`, `.docx`, `.jpg`, `.jpeg`, `.png` are
  accepted. The extension is cross-checked against the file's actual magic
  bytes (via `filetype`), so `malware.exe` renamed to `resume.pdf` is rejected
  with `415`.
- **Secure filenames** — client filenames pass through
  `werkzeug.utils.secure_filename`; path traversal attempts such as
  `../../etc/passwd.pdf` cannot escape the temp directory. The upload is written
  to a generated `tempfile` name, never to a client-controlled path.
- **No permanent storage** — each upload lives in a private temporary file and
  is deleted in a `finally` block, including on every error path. Deletion is
  retried briefly, since a library that failed to parse a file may still hold a
  handle on Windows. A test asserts no temp file survives any request.
- **No information leakage** — library errors and absolute paths are logged, not
  returned; unexpected exceptions become a generic `500`.

---

## Swapping in a different extraction engine

`app.py` only calls `extract_resume_data(text)`. To change how fields are
extracted, implement the interface and register it:

```python
# extractors/llm_extractor.py
from extractors import ExtractionEngine, register_engine


class LLMEngine(ExtractionEngine):
    name = "llm"

    def extract(self, text):
        # call a model, parse its reply
        return {
            "candidate_name": ...,
            "email": ...,
            "skills": [...],
            "education": [...],
            "experience": [...],
        }


register_engine(LLMEngine)
```

Then select it without any code change in the API layer:

```bash
EXTRACTION_ENGINE=llm python app.py
```

A per-request override is also possible — `extract_resume_data(text,
engine="llm")` — if you ever want to A/B two engines behind one endpoint.

### How the rule-based engine works

1. `utils/text_utils.normalize_text` normalises unicode, line endings and
   whitespace runs.
2. `split_sections` maps ~60 header aliases (`WORK EXPERIENCE`,
   `Professional Experience`, `Employment History`, ...) onto canonical section
   names, keeping everything above the first header as the `_preamble` where the
   name and contact details live.
3. Each extractor works on its own section, with a whole-document fallback for
   resumes that have no headers at all:
   - **email** — regex, with OCR false positives filtered out.
   - **name** — an explicit `Name:` label, else the first name-shaped line in
     the preamble (rejecting lines containing digits, `@`, or role words), else
     derived from the e-mail local part.
   - **skills** — the skills section is split on commas/pipes/bullets and kept
     verbatim (so niche tools survive), then a ~200-entry dictionary is matched
     across the whole document to catch skills mentioned only in bullet points.
     Aliases are normalised (`nodejs` → `Node.js`) and short ambiguous names
     (`C`, `R`, `Go`) are only trusted inside an explicit skills section.
   - **education** / **experience** — the section is split into one block per
     entry, then each block's segments are classified as degree/institution or
     title/company/location using keyword sets, with dates parsed by a shared
     date-range regex.

### Known limitations

Deliberate trade-offs for a simple first version:

- Multi-column PDF layouts can interleave text; PyMuPDF reads in document order.
- Legacy `.doc` (not `.docx`) is not supported — the error message says so.
- OCR quality depends on scan resolution; images are upscaled towards ~300 DPI
  and auto-contrasted first, but low-quality photos still parse poorly. The
  extractors tolerate the usual Tesseract artefacts - spaces inserted around
  "@", dropped colons after group labels, dropped commas between skills - but
  badly mangled words cannot be recovered.
- Rule-based classification favours common resume conventions. Unusual layouts
  may mis-assign a company as a title or leave a field empty. This is the main
  reason the extraction layer is swappable.
- `experience[].location` is only filled when the city sits beside the title or
  employer on the same line, since a lone capitalised word is too ambiguous.
- A hyphen is legal in an e-mail local part, so `"Email id-me@x.com"` is only
  trimmed to `me@x.com` when a contact label directly precedes the address.
- Phone numbers, LinkedIn URLs and certifications are parsed into sections but
  not returned, since the response contract fixes the five documented fields.
  Add them to `RuleBasedEngine.extract` when the contract allows it.
