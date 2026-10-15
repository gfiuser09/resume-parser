"""Case-study extraction: OCR'd text in, structured case-study fields out.

A Groq-hosted LLM reads the raw OCR text (noisy, possibly spanning several
pages) and returns the fields a case-study submission form needs. Word-count
ranges are stated in the prompt; the max side is also enforced server-side
since an LLM's compliance with "max N words" is a strong suggestion, not a
guarantee.
"""

from utils.errors import GroqError, GroqNotConfigured
from utils.groq_client import chat_json, chat_json_vision

#: field -> (min words, max words), as specified by the case-study form.
WORD_LIMITS = {
    "situation": (30, 200),
    "process": (25, 200),
    "results": (25, 200),
}

FIELDS = ("title", "client_name", "situation", "process", "results")

EMPTY_RESULT = {
    "title": "",
    "client_name": "",
    "situation": "",
    "process": "",
    "results": "",
    "word_counts": {"situation": 0, "process": 0, "results": 0},
}

#: OCR text past this length is truncated before being sent to the model, to
#: keep requests well inside the context window of small/fast Groq models.
MAX_INPUT_CHARS = 24000

SYSTEM_PROMPT = """You turn the OCR-extracted text of a scanned case-study document into a \
structured JSON record for a case-study submission form.

The document may span multiple pages, and the OCR text may contain scanning noise: \
misread characters, broken line wraps, repeated headers/footers, and page numbers. \
Read past this noise and reconstruct the coherent underlying narrative.

Produce a JSON object with exactly these keys:
- "title": a short, specific title for the case study. Reuse the document's own title \
if it states one, otherwise write one that names the client/industry and the problem solved.
- "client_name": the client or organisation the work was done for, if the document names \
one; otherwise an empty string. Never invent a name.
- "situation": what existed before the work started - the problem, context, or starting \
point. Between 30 and 200 words.
- "process": the approach taken to address the situation - what was actually done. \
Between 25 and 200 words.
- "results": what was measurably achieved - outcomes and metrics. Between 25 and 200 \
words. Use only figures that appear in the text; never fabricate statistics.

Write situation/process/results as flowing prose paragraphs, not bullet lists, grounded \
only in facts present in the source text. If the text does not cleanly separate situation \
from process from results, make the best reasonable split based on context and \
chronology rather than leaving a field empty.

Respond with the JSON object only - no markdown fences, no commentary.
"""


def _user_prompt(text):
    if len(text) > MAX_INPUT_CHARS:
        text = text[:MAX_INPUT_CHARS] + "\n[TEXT TRUNCATED]"
    return f"OCR TEXT:\n'''\n{text}\n'''"


def _clamp_to_max_words(text, max_words):
    """Trim *text* to at most *max_words*, preferring a sentence boundary."""
    words = text.split()
    if len(words) <= max_words:
        return text
    truncated = " ".join(words[:max_words])
    cut = truncated.rfind(". ")
    return truncated[: cut + 1] if cut > len(truncated) // 2 else truncated


EXPAND_SYSTEM_PROMPT = """You lengthen one paragraph of a case-study submission so it meets a \
minimum word count, using only facts grounded in the SOURCE TEXT provided. Never invent facts, \
numbers, or claims that are not present in the source. Add genuine supporting detail (context, \
specifics, elaboration) rather than padding or repeating what is already there.

Respond with a JSON object: {"text": "..."}. The final text must be between MIN_WORDS and \
MAX_WORDS words.
"""


def _expand_field(field, current_text, source_text):
    min_words, max_words = WORD_LIMITS[field]
    system = EXPAND_SYSTEM_PROMPT.replace("MIN_WORDS", str(min_words)).replace(
        "MAX_WORDS", str(max_words)
    )
    user = (
        f"SOURCE TEXT:\n'''\n{source_text}\n'''\n\n"
        f"CURRENT {field.upper()} PARAGRAPH ({len(current_text.split())} words, "
        f"needs at least {min_words}):\n'''\n{current_text}\n'''"
    )
    try:
        raw = chat_json(system, user)
    except (GroqError, GroqNotConfigured):
        return current_text
    text = raw.get("text") if isinstance(raw, dict) else None
    return text.strip() if isinstance(text, str) and text.strip() else current_text


def ensure_min_words(data, source_text):
    """Best-effort top-up of any field under its minimum word count.

    Costs one extra Groq call per short field, grounded in *source_text* so
    no facts are invented; most inputs already clear the minimum on the
    first pass, so this only adds latency when needed. Falls back to the
    original text for a field if the expansion call itself fails.
    """
    for field, (min_words, max_words) in WORD_LIMITS.items():
        if data["word_counts"][field] < min_words:
            expanded = _expand_field(field, data[field], source_text)
            expanded = _clamp_to_max_words(expanded, max_words)
            data[field] = expanded
            data["word_counts"][field] = len(expanded.split())
    return data


VISION_SYSTEM_PROMPT = """You read the attached image(s) of a case-study document - scanned \
pages or a photographed printout - and turn them into a structured JSON record for a \
case-study submission form.

The document may span multiple page images, and may be a noisy scan or photo: skewed angles, \
glare, misread characters, repeated headers/footers, and page numbers. Read past this noise \
and reconstruct the coherent underlying narrative.

Produce a JSON object with exactly these keys:
- "title": a short, specific title for the case study. Reuse the document's own title \
if it states one, otherwise write one that names the client/industry and the problem solved.
- "client_name": the client or organisation the work was done for, if the document names \
one; otherwise an empty string. Never invent a name.
- "situation": what existed before the work started - the problem, context, or starting \
point. Between 30 and 200 words.
- "process": the approach taken to address the situation - what was actually done. \
Between 25 and 200 words.
- "results": what was measurably achieved - outcomes and metrics. Between 25 and 200 \
words. Use only figures that appear in the images; never fabricate statistics.

Write situation/process/results as flowing prose paragraphs, not bullet lists, grounded \
only in facts visible in the images. If the document does not cleanly separate situation \
from process from results, make the best reasonable split based on context and \
chronology rather than leaving a field empty.

Respond with the JSON object only - no markdown fences, no commentary.
"""


def extract_case_study_data_from_images(images):
    """Return the structured case-study fields read directly from page *images*.

    *images* is a list of ``(mime_type, raw_bytes)`` tuples (see
    :func:`parsers.case_study_parser.extract_page_images`). A vision model
    performs OCR and extraction in one call, which sidesteps local Tesseract
    OCR entirely - the CPU-bound step that makes this endpoint slow on
    CPU-throttled hosts.
    """
    if not images:
        return {**EMPTY_RESULT, "word_counts": dict(EMPTY_RESULT["word_counts"])}

    raw = chat_json_vision(
        VISION_SYSTEM_PROMPT, "Extract the case study fields from these page images.", images
    )
    if not isinstance(raw, dict):
        raw = {}

    data = {}
    for field in FIELDS:
        value = raw.get(field)
        data[field] = value.strip() if isinstance(value, str) else ""

    for field, (_, max_words) in WORD_LIMITS.items():
        data[field] = _clamp_to_max_words(data[field], max_words)

    data["word_counts"] = {field: len(data[field].split()) for field in WORD_LIMITS}
    return data


def extract_case_study_data(text):
    """Return the structured case-study fields extracted from OCR'd *text*."""
    text = (text or "").strip()
    if not text:
        return {**EMPTY_RESULT, "word_counts": dict(EMPTY_RESULT["word_counts"])}

    raw = chat_json(SYSTEM_PROMPT, _user_prompt(text))
    if not isinstance(raw, dict):
        raw = {}

    data = {}
    for field in FIELDS:
        value = raw.get(field)
        data[field] = value.strip() if isinstance(value, str) else ""

    for field, (_, max_words) in WORD_LIMITS.items():
        data[field] = _clamp_to_max_words(data[field], max_words)

    data["word_counts"] = {field: len(data[field].split()) for field in WORD_LIMITS}
    return data


__all__ = [
    "EMPTY_RESULT",
    "WORD_LIMITS",
    "extract_case_study_data",
    "extract_case_study_data_from_images",
    "ensure_min_words",
]
