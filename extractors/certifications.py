"""Sustainability / ESG certification extraction.

Two passes, mirroring :mod:`extractors.skills`:

1. A dictionary of recognised credentials (LEED, GRI, ISO 14001, ...) is matched
   across the whole document, since certifications are often named inline in a
   summary or job bullet rather than in their own section.
2. Items listed under a "Certifications" heading are kept when they mention a
   sustainability term, so credentials no dictionary knows about still surface.

Non-sustainability certifications (AWS, Scrum, CFA, ...) are deliberately
excluded - the field is specifically for sustainability credentials.
"""

import re

from utils.text_utils import clean_line, get_section, iter_lines

#: canonical credential name -> aliases/spellings
CERTIFICATION_DICTIONARY = {
    # --- green building ---
    "LEED AP": ["leed ap", "leed accredited professional"],
    "LEED Green Associate": ["leed green associate", "leed ga"],
    "LEED": ["leed"],
    "BREEAM": ["breeam"],
    "WELL AP": ["well ap", "well accredited professional"],
    "Fitwel Ambassador": ["fitwel ambassador", "fitwel"],
    "EDGE Expert": ["edge expert", "edge auditor"],
    "IGBC AP": ["igbc ap", "igbc accredited professional", "igbc"],
    "GRIHA CP": ["griha cp", "griha certified professional", "griha"],
    "Envision SP": ["envision sp", "envision sustainability professional"],
    # --- reporting / disclosure frameworks ---
    "GRI Certified": ["gri certified", "gri standards", "gri professional",
                      "certified sustainability reporting"],
    "SASB FSA Credential": ["sasb fsa", "fsa credential", "sasb"],
    "TCFD": ["tcfd", "task force on climate-related financial disclosures"],
    "CSRD / ESRS": ["csrd", "esrs", "european sustainability reporting standards"],
    "CDP Accredited Provider": ["cdp accredited", "cdp provider", "cdp"],
    "IFRS S1/S2": ["ifrs s1", "ifrs s2", "issb"],
    "B Corp": ["b corp", "b-corp", "bcorp", "b impact assessment"],
    "GRESB": ["gresb"],
    # --- ISO standards ---
    "ISO 14001": ["iso 14001", "iso14001", "iso 14001:2015"],
    "ISO 14064": ["iso 14064", "iso14064"],
    "ISO 14067": ["iso 14067", "iso14067"],
    "ISO 50001": ["iso 50001", "iso50001"],
    "ISO 45001": ["iso 45001", "iso45001"],
    "ISO 14001 Lead Auditor": ["iso 14001 lead auditor", "ems lead auditor"],
    # --- carbon / energy ---
    "GHG Protocol": ["ghg protocol", "greenhouse gas protocol"],
    "Certified Energy Manager": ["certified energy manager", "cem certification"],
    "Certified Energy Auditor": ["certified energy auditor", "cea certification"],
    "Certified Measurement & Verification Professional": ["cmvp"],
    "BEE Certified Energy Auditor": ["bee certified energy auditor",
                                     "bee energy auditor", "bee energy manager"],
    "PAS 2060": ["pas 2060", "pas2060"],
    "Carbon Trust Standard": ["carbon trust standard", "carbon trust"],
    "SBTi": ["sbti", "science based targets"],
    "Carbon Literacy": ["carbon literacy"],
    "Certified Carbon Accountant": ["certified carbon accountant",
                                    "carbon accounting certificate"],
    # --- EHS / environment ---
    "IEMA": ["iema", "institute of environmental management"],
    "NEBOSH Environmental": ["nebosh environmental", "nebosh certificate in environmental"],
    "OSHA": ["osha 30", "osha 10", "osha certification"],
    "Certified Environmental Professional": ["certified environmental professional",
                                             "cep certification"],
    "HAZWOPER": ["hazwoper"],
    # --- sustainable finance / general ---
    "CFA Certificate in ESG Investing": ["certificate in esg investing",
                                         "cfa esg", "esg investing certificate"],
    "Sustainability and Climate Risk (SCR)": ["sustainability and climate risk",
                                              "garp scr", "scr certificate"],
    "Certified Sustainability Practitioner": ["certified sustainability practitioner",
                                              "certified sustainability professional",
                                              "csr professional"],
    "Life Cycle Assessment (LCA) Certification": ["lca certification",
                                                  "certified lca practitioner"],
    "Fairtrade": ["fairtrade certification", "fair trade certified"],
    "FSC": ["fsc certified", "forest stewardship council"],
    "Cradle to Cradle": ["cradle to cradle", "c2c certified"],
}

#: Terms that make an unrecognised certification count as sustainability-related.
SUSTAINABILITY_TERMS = re.compile(
    r"\b(?:sustainab\w*|esg|csr|carbon|climate|green|environment\w*|renewable|"
    r"solar|wind|energy|emission\w*|net[\s-]?zero|decarboni\w*|circular|"
    r"recycl\w*|waste|water|biodiversity|ecolog\w*|clean\s?tech|ehs|"
    r"greenhouse|ghg|lca|life\s?cycle)\b",
    re.IGNORECASE,
)

#: alias -> canonical name
_ALIASES = {}
for _canonical, _alias_list in CERTIFICATION_DICTIONARY.items():
    _ALIASES[_canonical.lower()] = _canonical
    for _alias in _alias_list:
        _ALIASES[_alias] = _canonical

_LEFT = r"(?<![A-Za-z0-9])"
_RIGHT = r"(?![A-Za-z0-9])"
#: Longest alias first, so "LEED Green Associate" wins over plain "LEED".
_PATTERNS = [
    (canonical, re.compile(_LEFT + re.escape(alias) + _RIGHT, re.IGNORECASE))
    for alias, canonical in sorted(_ALIASES.items(), key=lambda kv: -len(kv[0]))
]

#: Canonical names that are a prefix of a more specific credential.
_GENERIC = {"LEED", "CDP Accredited Provider", "IGBC AP", "GRIHA CP",
            "Carbon Trust Standard", "ISO 14001"}

_ITEM_SPLIT = re.compile(r"\s*[,;|]\s*|\s{3,}")
_ITEM_LABEL = re.compile(r"^[A-Za-z][A-Za-z /&+#.-]{0,40}:\s*")

#: An unrecognised item must look like a credential, not just mention a green
#: word - otherwise prose such as "agile development environments" qualifies.
CREDENTIAL_HINTS = re.compile(
    r"\b(?:certified|certificate|certification|certifications|accredited|"
    r"credential|diploma|licence|license|licensed|auditor|assessor|practitioner|"
    r"professional|associate|standard|specialist|training|trained|course|"
    r"workshop|masterclass|bootcamp|programme|program|fellowship|iso|nebosh|"
    r"osha|level\s?\d)\b",
    re.IGNORECASE,
)
MIN_ITEM_WORDS = 2

MAX_ITEM_CHARS = 90
MAX_CERTIFICATIONS = 15


def _listed_items(sections):
    """Yield raw items from the certification-ish sections of the resume."""
    body = "\n".join(
        part for part in (
            get_section(sections, "certifications"),
            get_section(sections, "awards"),
        ) if part
    )
    for line in iter_lines(body):
        line = _ITEM_LABEL.sub("", clean_line(line))
        for item in _ITEM_SPLIT.split(line):
            item = clean_line(item).strip(" .")
            if item:
                yield item


def extract_sustainability_certifications(text, sections=None):
    """Return sustainability/ESG certifications found in *text*.

    Returns an empty list when the resume has none - this field is common on
    sustainability-sector resumes and absent from most others.
    """
    sections = sections or {}
    text = text or ""
    found = {}  # lowercase key -> display name

    def add(name):
        if name and name.lower() not in found:
            found[name.lower()] = name

    # 1. Dictionary sweep over the whole document.
    matched_specific = set()
    for canonical, pattern in _PATTERNS:
        if not pattern.search(text):
            continue
        if canonical in _GENERIC and matched_specific:
            # Skip "LEED" when "LEED Green Associate" already matched.
            if any(canonical.split()[0] in other for other in matched_specific):
                continue
        add(canonical)
        if canonical not in _GENERIC:
            matched_specific.add(canonical)

    # 2. Unrecognised items from a certifications section, if clearly green.
    for item in _listed_items(sections):
        if len(item) > MAX_ITEM_CHARS or item.lower() in _ALIASES:
            continue
        if len(item.split()) < MIN_ITEM_WORDS:
            continue
        if any(pattern.search(item) for _, pattern in _PATTERNS):
            continue  # a known credential inside a longer phrase; already added
        if SUSTAINABILITY_TERMS.search(item) and CREDENTIAL_HINTS.search(item):
            add(item)

    return sorted(found.values(), key=str.lower)[:MAX_CERTIFICATIONS]
