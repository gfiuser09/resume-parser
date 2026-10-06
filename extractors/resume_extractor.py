"""The extraction layer: plain text in, structured candidate data out.

This module is deliberately isolated from Flask and from the file parsers. The
API talks to an :class:`ExtractionEngine`, so the rule-based implementation
below can later be replaced by an LLM- or spaCy-backed engine without touching
``app.py``: implement :meth:`ExtractionEngine.extract` and register it in
:mod:`extractors`.
"""

import re

from utils.text_utils import (
    clean_line,
    get_section,
    header_key,
    iter_lines,
    normalize_text,
    split_sections,
)

from .education import extract_education
from .experience import extract_experience
from .skills import extract_skills

# ---------------------------------------------------------------------------
# Contact details
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}"
)

#: A contact label sitting immediately before an address, with the label
#: word captured: "Email id-me@x.com" -> "email".
_EMAIL_LABEL_BEFORE_RE = re.compile(
    r"(e-?mail|gmail|mail|id|contact)\b[\s:.|-]*$", re.IGNORECASE
)
#: A label token the address regex swallowed into the local part.
_EMAIL_LABEL_PREFIX_RE = re.compile(
    r"^(e-?mail|gmail|mail|id|contact)[-._]+", re.IGNORECASE
)
#: Only these (label before, prefix in local part) pairs are stripped. The
#: "<mail word> id-" phrasing is common; a bare "contact: id-..." is not,
#: and "id-cards@" is a plausible real address, so it is left alone.
_STRIPPABLE_LABEL_PAIRS = {
    ("email", "id"), ("e-mail", "id"), ("mail", "id"), ("gmail", "id"),
}

#: "Name: John Doe" / "Candidate Name - John Doe"
NAME_LABEL_RE = re.compile(
    r"^(?:candidate\s+name|full\s+name|name)\s*[:\-]\s*(.+)$", re.IGNORECASE
)

#: A phone number trailing the name, e.g. "Uttam Kumar 9065880852".
_TRAILING_PHONE_RE = re.compile(
    r"[\s,|/()-]*(?:\+\d{1,3}[\s-]*)?(?:\(?\d{2,5}\)?[\s.-]*){2,}\d{2,}\s*$"
)

#: A single plausible name token: "John", "O'Brien", "Kumar-Singh", "J."
_NAME_TOKEN_RE = re.compile(r"^(?:[A-Z][a-z'’-]{1,19}|[A-Z]\.?|[A-Z]{2,20})$")

#: Words that disqualify a line from being the candidate's name.
_NOT_A_NAME = re.compile(
    r"\b(?:resume|curriculum\s+vitae|\bcv\b|profile|engineer|developer|manager|"
    r"analyst|designer|consultant|intern|student|scientist|architect|specialist|"
    r"address|phone|mobile|email|e-mail|linkedin|github|portfolio|objective|"
    r"summary|experience|education|skills)\b",
    re.IGNORECASE,
)

MAX_NAME_LINES = 12
MIN_NAME_TOKENS = 2
MAX_NAME_TOKENS = 4


#: OCR often inserts spaces around the "@" or the dots: "john.doe @example.com".
_OCR_EMAIL_NOISE_RE = re.compile(r"\s*@\s*|\s+\.\s*|\s*\.\s+")


def extract_email(text):
    """Return the first e-mail address in *text*, or an empty string.

    Tried twice: once on the text as-is, then on a copy with whitespace around
    "@" and "." removed, which is a common OCR artifact.
    """
    text = text or ""
    for candidate_text in (text, _repair_ocr_spacing(text)):
        email = _first_email(candidate_text)
        if email:
            return email
        if candidate_text is text and "@" not in text:
            break  # nothing to repair
    return ""


def _repair_ocr_spacing(text):
    """Close up spaces that OCR inserted around "@" and "." inside addresses."""
    def _close_up(match):
        return match.group(0).strip()

    return _OCR_EMAIL_NOISE_RE.sub(_close_up, text)


def _first_email(text):
    for match in EMAIL_RE.finditer(text):
        email = match.group(0).strip(" .,;:")
        # Reject obvious false positives from OCR noise.
        if len(email) > 254 or email.lower().endswith((".png", ".jpg", ".pdf")):
            continue
        return _strip_label_prefix(email, text[max(0, match.start() - 16):match.start()])
    return ""


def _strip_label_prefix(email, preceding_text):
    """Drop a label that ran into the address, e.g. "Email id-me@x.com".

    Hyphens are legal in a local part, so this only fires when the text just
    before the address is itself a contact label.
    """
    before = _EMAIL_LABEL_BEFORE_RE.search(preceding_text)
    if not before:
        return email

    local, _, domain = email.partition("@")
    prefix = _EMAIL_LABEL_PREFIX_RE.match(local)
    if not prefix:
        return email

    pair = (before.group(1).lower(), prefix.group(1).lower())
    if pair not in _STRIPPABLE_LABEL_PAIRS and pair[0] != pair[1]:
        return email

    trimmed = local[prefix.end():]
    if len(trimmed) >= 3:
        return f"{trimmed}@{domain}"
    return email


def _name_from_line(line):
    """Return *line* as a name if it looks like one, else an empty string."""
    candidate = clean_line(line).strip(" .")
    if not candidate or len(candidate) > 80:
        return ""
    if "@" in candidate:
        return ""
    # Resumes often put the phone number on the same line as the name.
    candidate = _TRAILING_PHONE_RE.sub("", candidate).strip(" .,|")
    if not candidate or any(ch.isdigit() for ch in candidate):
        return ""
    if header_key(candidate) or _NOT_A_NAME.search(candidate):
        return ""

    tokens = candidate.replace(",", " ").split()
    if not MIN_NAME_TOKENS <= len(tokens) <= MAX_NAME_TOKENS:
        return ""
    if not all(_NAME_TOKEN_RE.match(token) for token in tokens):
        return ""

    # Resumes often shout the name in capitals; present it in title case.
    if candidate.isupper():
        return " ".join(token.capitalize() for token in tokens)
    return " ".join(tokens)


def _name_from_email(email):
    """Derive a best-effort name from an e-mail local part."""
    local = (email or "").split("@")[0]
    parts = [part for part in re.split(r"[._\-+0-9]+", local) if len(part) > 1]
    if len(parts) < 2:
        return ""
    return " ".join(part.capitalize() for part in parts[:MAX_NAME_TOKENS])


def extract_name(text, sections=None, email=""):
    """Return the candidate's name, or an empty string if none was found."""
    sections = sections or {}

    # 1. An explicit "Name:" label anywhere near the top wins.
    header = get_section(sections, "_preamble", "contact") or text or ""
    for line in list(iter_lines(header))[:MAX_NAME_LINES]:
        match = NAME_LABEL_RE.match(clean_line(line))
        if match:
            name = _name_from_line(match.group(1))
            if name:
                return name

    # 2. Otherwise the first name-shaped line in the header block.
    for line in list(iter_lines(header))[:MAX_NAME_LINES]:
        name = _name_from_line(line)
        if name:
            return name

    # 3. Last resort: infer it from the e-mail address.
    return _name_from_email(email)


# ---------------------------------------------------------------------------
# Extraction engines
# ---------------------------------------------------------------------------

class ExtractionEngine:
    """Interface every extraction engine implements.

    Subclass this and return the same dictionary shape to swap in a different
    strategy (LLM prompt, spaCy NER model, paid API, ...). The Flask layer only
    ever sees :meth:`extract`.
    """

    #: Short identifier used to select the engine at runtime.
    name = "base"

    def extract(self, text):
        """Return ``{candidate_name, email, skills, education, experience}``."""
        raise NotImplementedError

    def __repr__(self):
        return f"<{type(self).__name__} name={self.name!r}>"


class RuleBasedEngine(ExtractionEngine):
    """Regex and keyword driven extraction - no model, no network calls."""

    name = "rule-based"

    def extract(self, text):
        text = normalize_text(text)
        sections = split_sections(text)

        email = extract_email(text)
        return {
            "candidate_name": extract_name(text, sections, email),
            "email": email,
            "skills": extract_skills(text, sections),
            "education": extract_education(text, sections),
            "experience": extract_experience(text, sections),
        }


#: Shape returned for a document from which nothing could be recognised.
EMPTY_RESULT = {
    "candidate_name": "",
    "email": "",
    "skills": [],
    "education": [],
    "experience": [],
}
