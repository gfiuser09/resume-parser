"""Case-study extraction: OCR'd text in, structured case-study fields out.

A Groq-hosted LLM reads the raw OCR text (noisy, possibly spanning several
pages) and returns the fields a case-study submission form needs. Word-count
ranges are stated in the prompt; the max side is also enforced server-side
since an LLM's compliance with "max N words" is a strong suggestion, not a
guarantee.
"""

from utils.groq_client import chat_json

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


__all__ = ["EMPTY_RESULT", "WORD_LIMITS", "extract_case_study_data"]
