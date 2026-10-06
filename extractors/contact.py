"""Contact detail extraction: phone number, LinkedIn URL and location.

All three are optional - every function returns an empty string when the
resume does not carry the detail.
"""

import re

from utils.text_utils import clean_line, get_section, iter_lines

# ---------------------------------------------------------------------------
# Phone
# ---------------------------------------------------------------------------

_PHONE_LABEL_RE = re.compile(
    r"\b(?:phone|mobile|cell|tel|telephone|contact|whats\s?app|ph|no)\b",
    re.IGNORECASE,
)
#: A run of digits and phone punctuation, at least 8 characters long.
_PHONE_CANDIDATE_RE = re.compile(r"(?<![\d])(\+?\d[\d\s().\-]{6,20}\d)(?![\d])")
#: "2015 - 2019" has as many digits as a short phone number.
_TWO_YEARS_RE = re.compile(r"^(?:19|20)\d{2}\D+(?:19|20)\d{2}$")

MIN_PHONE_DIGITS = 9           # unlabelled, e.g. "9065880852"
MIN_LABELLED_PHONE_DIGITS = 7  # "Phone: 555-1234"
MAX_PHONE_DIGITS = 15          # E.164 upper bound


def _phone_from_line(line, labelled):
    for match in _PHONE_CANDIDATE_RE.finditer(line):
        candidate = match.group(1).strip(" .-")
        digits = re.sub(r"\D", "", candidate)
        minimum = MIN_LABELLED_PHONE_DIGITS if labelled else MIN_PHONE_DIGITS
        if not minimum <= len(digits) <= MAX_PHONE_DIGITS:
            continue
        if _TWO_YEARS_RE.match(candidate):
            continue  # a year range, not a number
        return re.sub(r"\s{2,}", " ", candidate)
    return ""


def extract_phone(text, sections=None):
    """Return the candidate's phone number, or an empty string.

    Lines carrying a label ("Phone:", "Mobile") are searched first and accept
    shorter numbers; unlabelled lines need at least
    :data:`MIN_PHONE_DIGITS` digits so year ranges are not mistaken for one.
    """
    sections = sections or {}
    header = get_section(sections, "_preamble", "contact")
    bodies = [header, text or ""] if header else [text or ""]

    for labelled in (True, False):
        for body in bodies:
            for line in iter_lines(body):
                if bool(_PHONE_LABEL_RE.search(line)) != labelled:
                    continue
                phone = _phone_from_line(line, labelled)
                if phone:
                    return phone
    return ""


# ---------------------------------------------------------------------------
# LinkedIn
# ---------------------------------------------------------------------------

_LINKEDIN_RE = re.compile(
    r"(?:https?://)?(?:[a-z]{2,4}\.)?linkedin\.com/(?P<kind>in|pub)/"
    r"(?P<slug>[A-Za-z0-9_%\-.]{2,100})",
    re.IGNORECASE,
)
#: OCR likes to insert spaces around "/" and "." inside URLs.
_URL_NOISE_RE = re.compile(r"\s*/\s*|\s+\.\s*|\s*\.\s+")


def _repair_url_spacing(text):
    return _URL_NOISE_RE.sub(lambda m: m.group(0).strip(), text)


def extract_linkedin_url(text):
    """Return a normalised LinkedIn profile URL, or an empty string."""
    text = text or ""
    for candidate in (text, _repair_url_spacing(text)):
        match = _LINKEDIN_RE.search(candidate)
        if match:
            slug = match.group("slug").rstrip(".,;:/)")
            if slug.lower() in {"in", "pub", "company", "jobs"}:
                continue
            return f"https://www.linkedin.com/{match.group('kind').lower()}/{slug}"
        if "linkedin" not in text.lower():
            break
    return ""


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------

#: Known place names, so a bare line like "NEW DELHI" can be recognised without
#: mistaking the candidate's own name for a city. Extend freely - matching is
#: case-insensitive and falls back to the "City, Region" comma form below.
PLACES = {
    # --- India ---
    "new delhi", "delhi", "noida", "gurgaon", "gurugram", "faridabad", "ghaziabad",
    "mumbai", "navi mumbai", "thane", "pune", "nagpur", "nashik", "bangalore",
    "bengaluru", "mysore", "mysuru", "chennai", "coimbatore", "madurai",
    "hyderabad", "secunderabad", "warangal", "kolkata", "howrah", "ahmedabad",
    "surat", "vadodara", "rajkot", "gandhinagar", "jaipur", "jodhpur", "udaipur",
    "lucknow", "kanpur", "varanasi", "prayagraj", "agra", "patna", "ranchi",
    "bhubaneswar", "cuttack", "guwahati", "shillong", "bhopal", "indore",
    "gwalior", "jabalpur", "raipur", "chandigarh", "ludhiana", "amritsar",
    "jalandhar", "dehradun", "shimla", "srinagar", "jammu", "kochi", "cochin",
    "thiruvananthapuram", "trivandrum", "kozhikode", "thrissur", "mangalore",
    "hubli", "belgaum", "vijayawada", "visakhapatnam", "vizag", "guntur",
    "tirupati", "trichy", "tiruchirappalli", "salem", "vellore", "goa", "panaji",
    # --- rest of the world ---
    "london", "manchester", "birmingham", "edinburgh", "dublin", "paris", "berlin",
    "munich", "frankfurt", "hamburg", "amsterdam", "rotterdam", "brussels",
    "zurich", "geneva", "vienna", "madrid", "barcelona", "lisbon", "rome",
    "milan", "stockholm", "oslo", "copenhagen", "helsinki", "warsaw", "prague",
    "budapest", "athens", "istanbul", "dubai", "abu dhabi", "doha", "riyadh",
    "jeddah", "kuwait city", "manama", "muscat", "tel aviv", "cairo", "nairobi",
    "lagos", "accra", "johannesburg", "cape town", "new york", "new york city",
    "nyc", "brooklyn", "boston", "chicago", "austin", "dallas", "houston",
    "atlanta", "miami", "denver", "seattle", "portland", "san francisco",
    "san jose", "palo alto", "mountain view", "sunnyvale", "los angeles",
    "san diego", "phoenix", "las vegas", "washington", "philadelphia",
    "pittsburgh", "detroit", "minneapolis", "toronto", "vancouver", "montreal",
    "calgary", "ottawa", "mexico city", "sao paulo", "rio de janeiro",
    "buenos aires", "santiago", "bogota", "lima", "sydney", "melbourne",
    "brisbane", "perth", "auckland", "wellington", "singapore", "hong kong",
    "tokyo", "osaka", "kyoto", "seoul", "beijing", "shanghai", "shenzhen",
    "taipei", "bangkok", "jakarta", "kuala lumpur", "manila", "hanoi",
    "ho chi minh city", "colombo", "dhaka", "kathmandu", "karachi", "lahore",
    "islamabad",
    # --- countries / regions ---
    "india", "united states", "usa", "us", "uk", "united kingdom", "england",
    "scotland", "wales", "ireland", "canada", "australia", "new zealand",
    "germany", "france", "spain", "portugal", "italy", "netherlands", "belgium",
    "switzerland", "austria", "sweden", "norway", "denmark", "finland", "poland",
    "czechia", "hungary", "greece", "turkey", "israel", "uae",
    "united arab emirates", "qatar", "saudi arabia", "kuwait", "bahrain", "oman",
    "egypt", "kenya", "nigeria", "ghana", "south africa", "brazil", "argentina",
    "chile", "colombia", "peru", "mexico", "japan", "south korea", "china",
    "taiwan", "thailand", "indonesia", "malaysia", "philippines", "vietnam",
    "sri lanka", "bangladesh", "nepal", "pakistan", "singapore", "remote",
}

#: "DOB:08/02/2003" style fragments that sit next to a city on one-page resumes.
#: Single-word label only, so "NEW DELHI DOB:08/02/2003" keeps the city.
_INLINE_LABEL_RE = re.compile(r"\b[A-Za-z][A-Za-z]{0,19}\s*:\s*\S+")

#: "Bangalore, India" / "NEW DELHI" / "San Jose, CA"
_PLACE_WORD = r"[A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,2}"
_LOCATION_RE = re.compile(rf"^{_PLACE_WORD}(?:,\s*{_PLACE_WORD})?$")

MAX_LOCATION_LINES = 10


def _is_place(fragment):
    return fragment.strip().lower() in PLACES


def _location_from_line(line, skip):
    """Return *line* as a location if it looks like one, else ``""``."""
    candidate = _INLINE_LABEL_RE.sub("", clean_line(line)).strip(" ,|-")
    if not candidate or len(candidate) > 60:
        return ""
    if candidate.lower() in skip or any(ch.isdigit() for ch in candidate):
        return ""
    if "@" in candidate or "/" in candidate:
        return ""
    if not _LOCATION_RE.match(candidate):
        return ""

    if candidate.isupper():
        candidate = candidate.title()

    parts = [part.strip() for part in candidate.split(",")]
    # A comma form ("City, Country") is distinctive enough on its own; a bare
    # single name has to be a place we know, or it could be anyone's surname.
    if len(parts) > 1 and any(_is_place(part) for part in parts):
        return candidate
    if len(parts) > 1 and all(len(part.split()) <= 3 for part in parts):
        return candidate
    return candidate if _is_place(candidate) else ""


def extract_current_location(text, sections=None, experience=None, name="",
                             preferred=""):
    """Return the candidate's current location, or an empty string.

    Precedence: the location on the job held *now* (*preferred*), then the
    header block, then any older job's location. A previous employer's city is
    deliberately ranked below the header, since it may no longer be where the
    candidate lives.
    """
    sections = sections or {}
    if preferred:
        return preferred

    skip = {name.strip().lower()} if name else set()
    header = get_section(sections, "_preamble", "contact") or text or ""
    for line in list(iter_lines(header))[:MAX_LOCATION_LINES]:
        location = _location_from_line(line, skip)
        if location:
            return location

    for entry in experience or []:
        if entry.get("location"):
            return entry["location"]
    return ""
