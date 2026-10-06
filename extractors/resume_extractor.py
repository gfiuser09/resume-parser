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

from .certifications import extract_sustainability_certifications
from .contact import extract_current_location, extract_linkedin_url, extract_phone
from .education import extract_education
from .experience import extract_experience
from .focus import extract_focus_area
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
# Bio and current role
# ---------------------------------------------------------------------------

MAX_BIO_CHARS = 1200

#: Durations that mean "still working here".
_ONGOING_RE = re.compile(r"\b(?:present|current(?:ly)?|now|ongoing|to\s?date)\b",
                         re.IGNORECASE)


def extract_bio(text, sections=None):
    """Return the candidate's summary/objective paragraph, or an empty string.

    Line breaks inside the section are collapsed, since PDF extraction wraps
    mid-sentence and the field is meant to be stored as one paragraph.
    """
    sections = sections or {}
    body = get_section(sections, "summary")
    if not body:
        return ""

    paragraph = " ".join(clean_line(line) for line in iter_lines(body))
    paragraph = re.sub(r"\s{2,}", " ", paragraph).strip()
    if len(paragraph) <= MAX_BIO_CHARS:
        return paragraph
    # Trim to the last sentence that fits, rather than mid-word.
    cut = paragraph[:MAX_BIO_CHARS]
    stop = cut.rfind(". ")
    return (cut[:stop + 1] if stop > MAX_BIO_CHARS // 2 else cut).strip()


def _current_entry(experience):
    """Return the job the candidate currently holds, or the most recent one."""
    for entry in experience or []:
        if _ONGOING_RE.search(entry.get("duration", "")):
            return entry
    # Resumes are reverse-chronological, so the first entry is the latest.
    return (experience or [None])[0]


def extract_current_job_title(text, sections=None, experience=None):
    """Return the current job title, falling back to a headline role line."""
    entry = _current_entry(experience)
    if entry and entry.get("title"):
        return entry["title"]
    return _headline_role(sections)


def extract_current_company(experience=None):
    """Return the current employer, or an empty string."""
    entry = _current_entry(experience)
    return entry.get("company", "") if entry else ""


def _headline_role(sections):
    """Find a role stated under the name, e.g. "Senior Backend Engineer"."""
    from .experience import looks_like_title

    header = get_section(sections or {}, "_preamble")
    for line in list(iter_lines(header))[:6]:
        for segment in re.split(r"\s*[|,]\s*|\s{3,}", clean_line(line)):
            segment = segment.strip(" .")
            if not segment or "@" in segment or any(c.isdigit() for c in segment):
                continue
            if looks_like_title(segment):
                return segment
    return ""

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
        """Return the field set documented by :data:`EMPTY_RESULT`."""
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
        name = extract_name(text, sections, email)
        # Experience is computed first: the current role, employer and location
        # are all read off the most recent entry.
        experience = extract_experience(text, sections)

        return {
            "candidate_name": name,
            "email": email,
            "phone": extract_phone(text, sections),
            "linkedin_url": extract_linkedin_url(text),
            "current_location": extract_current_location(
                text, sections, experience, name,
                preferred=(_current_entry(experience) or {}).get("location", ""),
            ),
            "current_job_title": extract_current_job_title(text, sections, experience),
            "current_company": extract_current_company(experience),
            "bio": extract_bio(text, sections),
            "focus_area": extract_focus_area(text, sections, experience),
            "skills": extract_skills(text, sections),
            "sustainability_certifications":
                extract_sustainability_certifications(text, sections),
            "education": extract_education(text, sections),
            "experience": experience,
        }


#: Shape returned for a document from which nothing could be recognised. Also
#: the canonical field order of the API response.
EMPTY_RESULT = {
    "candidate_name": "",
    "email": "",
    "phone": "",
    "linkedin_url": "",
    "current_location": "",
    "current_job_title": "",
    "current_company": "",
    "bio": "",
    "focus_area": [],
    "skills": [],
    "sustainability_certifications": [],
    "education": [],
    "experience": [],
}
