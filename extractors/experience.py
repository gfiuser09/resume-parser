"""Work experience extraction.

Rule-based: locate the experience section, split it into one block per job,
then classify each block into a job title, a company, a duration and the
bullet-point description underneath.

Each entry is returned as::

    {"title": str, "company": str, "duration": str, "location": str,
     "description": str}
"""

import re

from utils.text_utils import (
    DATE_RANGE_RE,
    MONTH_SPAN_RE,
    YEAR_RE,
    clean_line,
    format_date_range,
    format_month_span,
    get_section,
    is_date_only,
    iter_lines,
    strip_trailing_date,
    split_entries,
)

#: Role nouns that identify a job title.
TITLE_KEYWORDS = [
    "engineer", "developer", "programmer", "architect", "analyst", "scientist",
    "designer", "consultant", "administrator", "administrater", "specialist",
    "manager", "director", "president", "founder", "co-founder", "partner",
    "lead", "head", "chief", "officer", "supervisor", "coordinator",
    "associate", "assistant", "executive", "intern", "internship", "trainee",
    "apprentice", "fellow", "researcher", "research assistant", "teaching assistant",
    "tester", "qa", "sre", "devops", "technician", "strategist", "marketer",
    "writer", "editor", "accountant", "recruiter", "advisor", "freelancer",
    "contractor", "volunteer", "cto", "ceo", "coo", "cfo", "vp",
]
_TITLE_RE = re.compile(r"\b(" + "|".join(TITLE_KEYWORDS) + r")s?\b", re.IGNORECASE)

#: Suffixes and nouns that identify a company name.
COMPANY_KEYWORDS = [
    "inc", "inc.", "llc", "l.l.c", "ltd", "ltd.", "limited", "llp", "plc",
    "pvt", "pvt.", "private", "corp", "corp.", "corporation", "co", "co.",
    "company", "gmbh", "s.a", "b.v", "ag", "oy", "ab",
    "technologies", "technology", "tech", "solutions", "systems", "services",
    "software", "labs", "laboratories", "studios", "studio", "consulting",
    "group", "holdings", "ventures", "partners", "industries", "enterprises",
    "digital", "media", "networks", "global", "international", "institute",
    "university", "college", "foundation", "bank", "agency", "startup",
]
_COMPANY_RE = re.compile(r"\b(" + "|".join(
    kw.replace(".", r"\.") for kw in COMPANY_KEYWORDS
) + r")\b", re.IGNORECASE)

#: Seniority words that may stand alone in front of a role noun.
SENIORITY = r"senior|sr\.?|junior|jr\.?|lead|principal|staff|chief|head|associate"
_SENIORITY_RE = re.compile(r"^(?:" + SENIORITY + r")\b", re.IGNORECASE)

#: Splits a header line such as "Backend Engineer | Acme Inc | Jan 2020 - Present".
_HEADER_SPLIT = re.compile(
    r"\s*[|•]\s*"            # pipe / bullet separators
    r"|\s*,\s*"              # commas
    r"|\s+(?:at|@|for)\s+"       # "Engineer at Acme"
    r"|\s+[-–—]\s+"          # spaced dashes
    r"|\s{3,}",              # column gaps from PDF/OCR extraction
    re.IGNORECASE,
)

_BULLET_START = re.compile(r"^\s*[-*•·▪◦‣⁃∙>]\s*")
_LOCATION_RE = re.compile(
    r"^(?:remote|hybrid|on-?site|[A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,2}"
    r"(?:,\s*[A-Z]{2,})?)$"
)

#: "SKILLS USED: ...", "Tech Stack: ..." - a labelled line is description
#: content inside a job block, never a header.
_LABEL_LINE_RE = re.compile(r"^[A-Za-z][A-Za-z /&+#.-]{0,30}:\s*\S")

#: Work arrangements, which are locations rather than employers.
_WORK_MODE_RE = re.compile(r"^(?:remote|hybrid|on-?site|work from home|wfh)$",
                           re.IGNORECASE)

#: Prose connectors: a segment containing one is a sentence, not a company.
_PROSE_RE = re.compile(r"\b(?:and|with|using|the|for|to|of|in)\b", re.IGNORECASE)

MAX_ENTRIES = 15
MAX_DESCRIPTION_CHARS = 1200


def _looks_like_title(segment):
    """True when *segment* reads like a job title."""
    if not segment or len(segment) > 70:
        return False
    return bool(_TITLE_RE.search(segment) or _SENIORITY_RE.match(segment))


def _looks_like_company(segment):
    """True when *segment* reads like an employer name."""
    if not segment or len(segment) > 70:
        return False
    return bool(_COMPANY_RE.search(segment))


def _could_be_company(segment):
    """True when *segment* could plausibly be an employer name.

    Used when no company keyword ("Inc", "Technologies", ...) was found, so a
    name like "CreditXchange.AI" still lands in the right field instead of
    being mistaken for a location.
    """
    if not segment or len(segment) > 50 or len(segment.split()) > 5:
        return False
    if not segment[0].isupper():
        return False
    return not _PROSE_RE.search(segment)


def _duration(block):
    """Return the duration of a job block, e.g. ``"Jan 2020 - Present"``."""
    match = DATE_RANGE_RE.search(block)
    if match:
        return format_date_range(match)
    match = MONTH_SPAN_RE.search(block)
    if match:
        return format_month_span(match)
    years = YEAR_RE.findall(block)
    if years:
        return years[0] if len(years) == 1 else f"{years[0]} - {years[-1]}"
    return ""


def _is_bullet(line):
    return bool(_BULLET_START.match(line))


def _is_header_line(line):
    """True when *line* carries header fields rather than description prose."""
    if not line or _is_bullet(line):
        return False
    if is_date_only(line):
        return False  # a bare date line belongs to the entry above it
    if len(line) > 120:
        return False
    if _LABEL_LINE_RE.match(line):
        return False  # e.g. "SKILLS USED: PYTHON, MYSQL"
    # Sentences (ending in a full stop, many words) are description text.
    if line.rstrip().endswith(".") and len(line.split()) > 6:
        return False
    return True


def _group_entries(section_text):
    """Split an experience section into one block of text per job.

    Blank lines are only a hint: a single blank-line block often still contains
    several jobs, so the line-level rules are applied inside every block.
    """
    groups = []
    for block in split_entries(section_text) or [section_text]:
        groups.extend(_group_lines(block))
    return groups


def _group_lines(section_text):
    """Group consecutive lines into job blocks.

    A new job starts at a non-bullet header line that carries a date range or a
    job title, once the current block already has one.
    """
    groups = []
    current = []
    has_header = False

    for line in iter_lines(section_text):
        if _is_bullet(line):
            current.append(line)
            continue

        is_header = _is_header_line(line) and (
            _looks_like_title(line) or bool(DATE_RANGE_RE.search(line))
        )
        if is_header and has_header and current:
            groups.append("\n".join(current))
            current, has_header = [], False

        current.append(line)
        has_header = has_header or is_header

    if current:
        groups.append("\n".join(current))
    return groups


def _parse_entry(block):
    """Turn one job block into a structured entry, or ``None`` if unusable."""
    title = company = location = ""
    description = []
    leftovers = []

    for line in iter_lines(block):
        if _is_bullet(line):
            description.append(clean_line(line))
            continue

        # Prose lines (long, or full sentences) are description text.
        if not _is_header_line(line) and not is_date_only(line):
            description.append(clean_line(line))
            continue

        # A bare city name is only trustworthy next to the title or employer
        # ("Globex Solutions, Bangalore"); elsewhere it is description text.
        line_named_job = False

        for segment in _HEADER_SPLIT.split(line):
            segment = clean_line(segment).strip(" .")
            if not segment or is_date_only(segment):
                continue
            segment = strip_trailing_date(segment)
            if is_date_only(segment):
                continue
            if not title and _looks_like_title(segment):
                title = segment
                line_named_job = True
            elif not location and _WORK_MODE_RE.match(segment):
                location = segment
            elif not company and _looks_like_company(segment):
                company = segment
                line_named_job = True
            elif not company and _could_be_company(segment):
                company = segment
                line_named_job = True
            elif (
                line_named_job
                and not location
                and len(segment) <= 40
                and _LOCATION_RE.match(segment)
            ):
                location = segment
            else:
                leftovers.append(segment)

    # Fill the gaps from whatever is left over, preserving document order.
    for segment in leftovers[:]:
        if not company:
            company = segment
            leftovers.remove(segment)
            break
    for segment in leftovers[:]:
        if not title:
            title = segment
            leftovers.remove(segment)
            break

    description.extend(leftovers)
    if not (title or company):
        return None

    return {
        "title": title,
        "company": company,
        "duration": _duration(block),
        "location": location,
        "description": " ".join(
            part for part in dict.fromkeys(description) if part
        )[:MAX_DESCRIPTION_CHARS].strip(),
    }


def _fallback_blocks(text):
    """Find job-looking lines when the resume has no experience section."""
    blocks = []
    lines = list(iter_lines(text))
    for index, line in enumerate(lines):
        if _looks_like_title(line) and DATE_RANGE_RE.search(line):
            blocks.append("\n".join(lines[index:index + 3]))
    return blocks


def extract_experience(text, sections=None):
    """Return a list of structured work-experience entries found in *text*."""
    sections = sections or {}
    section_text = get_section(sections, "experience")

    blocks = _group_entries(section_text) if section_text else _fallback_blocks(text)

    entries = []
    seen = set()
    for block in blocks[:MAX_ENTRIES * 2]:
        entry = _parse_entry(block)
        if not entry:
            continue
        key = (entry["title"].lower(), entry["company"].lower(), entry["duration"])
        if key in seen:
            continue
        seen.add(key)
        entries.append(entry)
        if len(entries) >= MAX_ENTRIES:
            break
    return entries
