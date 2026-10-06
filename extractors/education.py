"""Education extraction.

Rule-based: locate the education section (or fall back to scanning the whole
document), split it into entries, then classify the parts of each entry as a
degree, an institution, a year or leftover detail.

Each entry is returned as::

    {"degree": str, "institution": str, "year": str, "details": str}
"""

import re

from utils.text_utils import (
    DATE_RANGE_RE,
    YEAR_RE,
    clean_line,
    format_date_range,
    get_section,
    is_date_only,
    iter_lines,
    strip_trailing_date,
    split_entries,
)

#: Degree names and abbreviations. Order matters only for readability.
DEGREE_PATTERNS = [
    r"b\.?\s?tech", r"m\.?\s?tech", r"b\.?\s?e\b", r"m\.?\s?e\b",
    r"b\.?\s?sc", r"m\.?\s?sc", r"b\.?\s?com", r"m\.?\s?com",
    r"b\.?\s?a\b", r"m\.?\s?a\b", r"b\.?\s?c\.?\s?a\b", r"m\.?\s?c\.?\s?a\b",
    r"b\.?\s?b\.?\s?a\b", r"m\.?\s?b\.?\s?a\b", r"b\.?\s?s\b", r"m\.?\s?s\b",
    r"ph\.?\s?d", r"doctorate", r"post\s?graduat\w*", r"under\s?graduat\w*",
    r"bachelor(?:'?s)?", r"master(?:'?s)?", r"associate(?:'?s)?\s+degree",
    r"diploma", r"certificate\s+course",
    r"high\s?school", r"higher\s+secondary", r"senior\s+secondary", r"secondary\s+school",
    r"intermediate", r"\bhsc\b", r"\bssc\b", r"\bcbse\b", r"\bicse\b",
    r"\b1[02]th\b", r"\bclass\s+1[02]\b",
]
_DEGREE_RE = re.compile("|".join(DEGREE_PATTERNS), re.IGNORECASE)

#: Words that mark a segment as the name of an institution.
INSTITUTION_KEYWORDS = [
    "university", "universidad", "college", "institute", "institution",
    "school", "academy", "polytechnic", "faculty", "campus",
    "iit", "nit", "iiit", "iim", "bits",
]
_INSTITUTION_RE = re.compile(
    r"\b(" + "|".join(INSTITUTION_KEYWORDS) + r")\b", re.IGNORECASE
)

_YEAR_RANGE_RE = re.compile(
    r"\b(19|20)\d{2}\s*(?:-|to|until|through|–|—)\s*"
    r"((?:19|20)\d{2}|present|current|ongoing|expected[\s\w]{0,12})\b",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_GRADE_RE = re.compile(
    r"\b(?:cgpa|gpa|grade|percentage|marks|aggregate)\b[\s:]*"
    r"[-:]?\s*([0-9]{1,3}(?:\.[0-9]{1,2})?\s*%?(?:\s*/\s*[0-9]{1,2}(?:\.[0-9])?)?)",
    re.IGNORECASE,
)
#: Personal details that often sit next to education on a one-page resume.
_PERSONAL_DETAIL_RE = re.compile(
    r"^(?:gender|sex|dob|d\.o\.b|date\s+of\s+birth|nationality|marital"
    r"|age|father|mother|guardian|address|phone|mobile|languages?)\b",
    re.IGNORECASE,
)
_SEGMENT_SPLIT = re.compile(r"\s*[,|]\s*|\s+•\s+|\s{3,}")

MAX_ENTRIES = 10


def _years(block):
    """Return a human-readable year or year range found in *block*."""
    match = DATE_RANGE_RE.search(block)
    if match:
        return format_date_range(match)
    years = YEAR_RE.findall(block)
    if years:
        return years[-1]
    return ""


def _looks_like_degree(segment):
    return bool(_DEGREE_RE.search(segment))


def _looks_like_institution(segment):
    return bool(_INSTITUTION_RE.search(segment))


#: Splits "B.Sc from Delhi University" into its degree and institution halves.
_JOINER_RE = re.compile(r"\s+(?:from|at|,\s*)\s*", re.IGNORECASE)


def _split_degree_institution(segment):
    """Split a run-on "<degree> from <institution>" segment into its two parts.

    Returns ``(degree, institution)``; either half may be an empty string when
    the segment does not have that shape.
    """
    if not (_looks_like_degree(segment) and _looks_like_institution(segment)):
        return "", ""
    parts = _JOINER_RE.split(segment, maxsplit=1)
    if len(parts) != 2:
        return "", ""
    head, tail = (part.strip(" .,") for part in parts)
    if _looks_like_degree(head) and _looks_like_institution(tail):
        # Drop a trailing "in 2017" style fragment from the institution half.
        tail = re.sub(r"\s+in\s+(?:19|20)\d{2}\b.*$", "", tail, flags=re.IGNORECASE)
        # ...and a preposition left dangling once a date was stripped.
        tail = re.sub(r"\s+(?:in|at|from|during|since)\s*$", "", tail, flags=re.IGNORECASE)
        return head, tail.strip(" .,")
    return "", ""


def _group_entries(section_text):
    """Split an education section into one block of text per qualification.

    Blank lines are only a hint - one block can still hold several degrees, so
    the line-level rules are applied inside every block.
    """
    groups = []
    for block in split_entries(section_text) or [section_text]:
        groups.extend(_group_lines(block))
    return groups


def _group_lines(section_text):
    """Group consecutive lines into qualification blocks.

    A new entry starts whenever a line repeats a role the current entry already
    has (a second degree line, a second institution).
    """
    groups = []
    current = []
    has_degree = has_institution = False

    for line in iter_lines(section_text):
        line_is_degree = _looks_like_degree(line)
        line_is_institution = _looks_like_institution(line)
        starts_new = (line_is_degree and has_degree) or (
            line_is_institution and has_institution
        )
        if starts_new and current:
            groups.append("\n".join(current))
            current, has_degree, has_institution = [], False, False

        current.append(line)
        has_degree = has_degree or line_is_degree
        has_institution = has_institution or line_is_institution

    if current:
        groups.append("\n".join(current))
    return groups


def _parse_entry(block):
    """Turn one education block into a structured entry, or ``None``."""
    degree = institution = ""
    details = []

    for line in iter_lines(block):
        for segment in _SEGMENT_SPLIT.split(clean_line(line)):
            segment = clean_line(segment).strip(" .")
            if not segment:
                continue
            if _PERSONAL_DETAIL_RE.match(segment):
                continue
            segment = strip_trailing_date(segment)
            if is_date_only(segment):
                continue

            head, tail = _split_degree_institution(segment)
            if head and not degree and _looks_like_degree(head):
                degree = head
                if tail and not institution:
                    institution = tail
                continue
            if not degree and _looks_like_degree(segment):
                degree = segment
            elif not institution and _looks_like_institution(segment):
                institution = segment
            elif not is_date_only(segment):
                details.append(segment)

    year = _years(block)
    grade = _GRADE_RE.search(block)
    if grade and not any(grade.group(0) in detail for detail in details):
        details.append(grade.group(0).strip())

    if not (degree or institution):
        return None

    return {
        "degree": degree,
        "institution": institution,
        "year": year,
        "details": "; ".join(dict.fromkeys(details))[:300],
    }


def _fallback_blocks(text):
    """Find education-looking lines when there is no education section."""
    blocks = []
    lines = list(iter_lines(text))
    for index, line in enumerate(lines):
        if _looks_like_degree(line) and (
            _looks_like_institution(line) or YEAR_RE.search(line)
        ):
            window = lines[index:index + 2]
            blocks.append("\n".join(window))
    return blocks


def extract_education(text, sections=None):
    """Return a list of structured education entries found in *text*."""
    sections = sections or {}
    section_text = get_section(sections, "education", "certifications")

    blocks = _group_entries(section_text) if section_text else _fallback_blocks(text)

    entries = []
    seen = set()
    for block in blocks[:MAX_ENTRIES * 2]:
        entry = _parse_entry(block)
        if not entry:
            continue
        key = (entry["degree"].lower(), entry["institution"].lower(), entry["year"])
        if key in seen:
            continue
        seen.add(key)
        entries.append(entry)
        if len(entries) >= MAX_ENTRIES:
            break
    return entries
