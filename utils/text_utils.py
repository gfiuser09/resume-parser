"""Plain-text helpers shared by the extraction layer.

Keeping the generic text plumbing (normalisation, section splitting, bullet
handling) here means the individual extractors stay small and focused.
"""

import re
import unicodedata

#: Canonical section name -> header aliases found in real resumes.
SECTION_ALIASES = {
    "contact": ["contact", "contact information", "contact details", "personal details",
                "personal information"],
    "summary": ["summary", "professional summary", "career summary", "profile",
                "about me", "about", "objective", "career objective", "overview"],
    "skills": ["skills", "technical skills", "core skills", "key skills", "skill set",
               "skills & interests", "technologies", "technical expertise",
               "areas of expertise", "competencies", "core competencies",
               "technical proficiencies", "tools & technologies"],
    "experience": ["experience", "work experience", "working experience",
                   "professional experience", "employment", "employment history",
                   "work history", "career history", "relevant experience",
                   "industry experience", "internships", "internship experience"],
    "education": ["education", "educational qualifications", "education & training",
                  "academic background", "academics", "academic qualifications",
                  "qualifications", "educational background", "education details"],
    "projects": ["projects", "project", "personal projects", "academic projects", "key projects",
                 "selected projects", "project experience"],
    "certifications": ["certifications", "certification", "certificates", "licenses",
                       "licenses & certifications", "courses", "training"],
    "awards": ["awards", "achievements", "honors", "honours", "accomplishments",
               "awards & achievements", "activities"],
    "publications": ["publications", "papers", "research"],
    "languages": ["languages", "language proficiency"],
    "interests": ["interests", "hobbies", "hobbies & interests", "extracurricular",
                  "extra curricular activities", "volunteer", "volunteering",
                  "volunteer experience"],
    "references": ["references", "referees"],
}

#: alias -> canonical name
_ALIAS_LOOKUP = {
    alias: canonical
    for canonical, aliases in SECTION_ALIASES.items()
    for alias in aliases
}

#: bullet glyphs commonly produced by Word/PDF exports
BULLET_CHARS = (
    "*->"
    "•·▪◦‣⁃∙"  # bullet, middot, squares, triangle
    "–—"                                # en dash, em dash
)

#: spaces that are not ASCII spaces (nbsp, en/em space, zero width, ...)
EXOTIC_SPACES = "           " \
                "    　​﻿"

_BULLET_RE = re.compile(r"^[\s" + re.escape(BULLET_CHARS) + r"]+")
_SPACE_RE = re.compile(r"[ \t" + re.escape(EXOTIC_SPACES) + r"]+")


def normalize_text(text):
    """Normalise unicode, line endings and runs of whitespace."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _SPACE_RE.sub(" ", text)
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)
    # collapse 3+ newlines down to a single blank line
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_line(line):
    """Strip bullets and trailing punctuation noise from a single line."""
    line = _BULLET_RE.sub("", line or "").strip()
    return line.strip(" \t;,")


def iter_lines(text, keep_empty=False):
    """Yield stripped lines of *text*, skipping blanks unless asked otherwise."""
    for raw in (text or "").split("\n"):
        line = raw.strip()
        if line or keep_empty:
            yield line


def header_key(line):
    """Return the canonical section name if *line* looks like a section header."""
    if not line:
        return None
    candidate = clean_line(line)
    if not candidate or len(candidate) > 60:
        return None

    stripped = candidate.rstrip(":").strip()
    # Headers rarely contain sentence punctuation or digits.
    if any(ch in stripped for ch in ".@/()") or any(ch.isdigit() for ch in stripped):
        return None

    key = re.sub(r"[^a-z& ]+", " ", stripped.lower())
    key = re.sub(r"\s+", " ", key).strip()
    if key in _ALIAS_LOOKUP and len(stripped.split()) <= 5:
        return _ALIAS_LOOKUP[key]
    return None


def split_sections(text):
    """Split a resume into ``{canonical_section: body_text}``.

    Content appearing before the first recognised header is returned under the
    ``"_preamble"`` key - that is where the name and contact details usually
    live.
    """
    sections = {"_preamble": []}
    current = "_preamble"

    for raw in (text or "").split("\n"):
        line = raw.strip()
        key = header_key(line)
        if key:
            current = key
            sections.setdefault(current, [])
            continue
        sections[current].append(line)

    return {name: "\n".join(body).strip() for name, body in sections.items()}


def get_section(sections, *names):
    """Return the first non-empty section body among *names*."""
    for name in names:
        body = sections.get(name)
        if body:
            return body
    return ""


def split_entries(section_text):
    """Split a section body into entry blocks separated by blank lines."""
    return [
        block.strip()
        for block in re.split(r"\n\s*\n", section_text or "")
        if block.strip()
    ]


#: Month names and abbreviations, for date parsing in the extractors.
MONTH_PATTERN = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)

#: Words candidates use for "still working here".
PRESENT_PATTERN = r"present|current(?:ly)?|now|ongoing|till\s+date|to\s+date|date"

_YEAR = r"(?:19|20)\d{2}"
_MONTH_YEAR = r"(?:(?:" + MONTH_PATTERN + r")\.?,?\s*)?" + _YEAR
_SEPARATOR = r"\s*(?:-|--|to|through|until|–|—)\s*"

#: A full date range: "Jan 2020 - Mar 2022", "2019 to Present", "05/2021-Now".
DATE_RANGE_RE = re.compile(
    r"(?P<start>" + _MONTH_YEAR + r"|\d{1,2}/" + _YEAR + r")"
    + _SEPARATOR +
    r"(?P<end>" + _MONTH_YEAR + r"|\d{1,2}/" + _YEAR + r"|"
    + PRESENT_PATTERN + r")",
    re.IGNORECASE,
)

#: A segment that is nothing but a date / date range (no real content).
DATE_ONLY_RE = re.compile(
    r"^\(?\s*(?:" + _MONTH_YEAR + r"|\d{1,2}/" + _YEAR + r")"
    r"(?:" + _SEPARATOR + r"(?:" + _MONTH_YEAR + r"|\d{1,2}/" + _YEAR + r"|"
    + PRESENT_PATTERN + r"))?\s*\)?[.,;]?$",
    re.IGNORECASE,
)

YEAR_RE = re.compile(r"\b" + _YEAR + r"\b")




_PRESENT_RE = re.compile(r"^(?:" + PRESENT_PATTERN + r")$", re.IGNORECASE)


def format_date_range(match):
    """Render a :data:`DATE_RANGE_RE` match as a tidy ``"Start - End"`` string."""
    start = (match.group("start") or "").strip(" ,.")
    end = (match.group("end") or "").strip(" ,.")
    if _PRESENT_RE.match(end):
        end = "Present"
    return f"{start} - {end}" if end else start


def is_date_only(segment):
    """True when *segment* carries no information beyond a date or date range.

    Also true for a lone "Present"/"Current", which is what is left over when a
    header line like "Jan 2020 - Present" is split on its dash.
    """
    segment = (segment or "").strip()
    if not segment:
        return True
    if DATE_ONLY_RE.match(segment):
        return True
    return bool(_PRESENT_RE.match(segment.strip("().,: ")))

#: "March - April 2025", "15 July - 15 Oct (2025)" - a month span sharing one year.
MONTH_SPAN_RE = re.compile(
    r"(?P<from>(?:\d{1,2}\s+)?(?:" + MONTH_PATTERN + r")\w*)\.?\s*"
    r"(?:-|--|to|through|until|–|—)\s*"
    r"(?P<to>(?:\d{1,2}\s+)?(?:" + MONTH_PATTERN + r")\w*)\.?,?\s*"
    r"[(\[]?\s*(?P<year>(?:19|20)\d{2})\s*[)\]]?",
    re.IGNORECASE,
)


#: A year at the very end of a segment, e.g. "Acme Corp 2019", "B.Tech(2027)".
_TRAILING_YEAR_RE = re.compile(r"[(\[]?\s*(?:19|20)\d{2}\s*[)\]]?$")

_MONTH_ONLY_RE = re.compile(r"(?:" + MONTH_PATTERN + r")\w*", re.IGNORECASE)


def format_month_span(match):
    """Render a :data:`MONTH_SPAN_RE` match as ``"March - April 2025"``."""
    start = match.group("from").strip(" .,")
    end = match.group("to").strip(" .,")
    return f"{start} - {end} {match.group('year')}"


def _is_pure_date(segment):
    """True when *segment* is only a date, in any of the supported shapes."""
    bare = segment.strip("()[] ")
    return bool(is_date_only(segment) or MONTH_SPAN_RE.fullmatch(bare))


def strip_trailing_date(segment):
    """Remove a date fragment stuck to the end of *segment*.

    ``"Limnox Technologies March-April(2025)"`` -> ``"Limnox Technologies"``.

    The date must sit at the very end and be preceded by real content, so a
    segment that is *only* a date is returned untouched for the caller to
    recognise with :func:`is_date_only`.
    """
    segment = (segment or "").strip()
    if not segment or _is_pure_date(segment):
        return segment

    end_of_content = len(segment.rstrip(" .,)]"))
    for pattern in (MONTH_SPAN_RE, DATE_RANGE_RE, _TRAILING_YEAR_RE):
        for match in pattern.finditer(segment):
            if match.start() == 0 or match.end() < end_of_content:
                continue  # not a trailing fragment
            candidate = segment[:match.start()].strip(" ,.|-([")
            if len(candidate) < 2 or not re.search(r"[A-Za-z]{2}", candidate):
                continue
            if _MONTH_ONLY_RE.fullmatch(candidate):
                continue  # what is left is itself a date remnant
            return candidate
    return segment
