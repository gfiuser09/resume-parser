"""Focus-area extraction.

A focus area is the *domain* someone works in, as distinct from the tools they
use: "Carbon Accounting" rather than "Excel", "Backend Development" rather than
"Django". Matching is dictionary-driven and weighted towards the headline parts
of the resume (summary, job titles, section headings), because a term mentioned
once in a bullet is weaker evidence of focus than one in a job title.

Both sustainability and general professional domains are covered, so the field
is useful whichever sector the resume comes from.
"""

import re

from utils.text_utils import get_section, iter_lines

#: canonical focus area -> aliases
FOCUS_DICTIONARY = {
    # --- climate / carbon ---
    "Carbon Accounting": ["carbon accounting", "ghg accounting", "carbon footprinting",
                          "emissions accounting", "carbon inventory"],
    "Net Zero Strategy": ["net zero", "net-zero", "decarbonisation", "decarbonization",
                          "carbon neutrality"],
    "Climate Risk": ["climate risk", "climate resilience", "climate adaptation",
                     "physical risk", "transition risk"],
    "Carbon Markets": ["carbon markets", "carbon credits", "carbon offset",
                       "carbon trading", "emissions trading"],
    "Climate Policy": ["climate policy", "climate advocacy", "climate negotiation"],
    # --- ESG / reporting ---
    "ESG Reporting": ["esg reporting", "esg disclosure", "sustainability reporting",
                      "non-financial reporting", "brsr", "integrated reporting",
                      "esg analyst", "sustainability analyst"],
    "ESG Strategy": ["esg strategy", "sustainability strategy", "esg advisory",
                     "sustainability consulting"],
    "ESG Data & Analytics": ["esg data", "esg analytics", "sustainability analytics",
                             "esg ratings"],
    "Double Materiality": ["double materiality", "materiality assessment"],
    "Sustainable Finance": ["sustainable finance", "green finance", "green bonds",
                            "impact investing", "esg investing", "blended finance"],
    "Corporate Social Responsibility": ["corporate social responsibility", "csr"],
    "Social Impact": ["social impact", "impact measurement", "community development",
                      "social performance"],
    # --- environment / operations ---
    "Renewable Energy": ["renewable energy", "solar energy", "wind energy",
                         "solar pv", "clean energy", "green hydrogen"],
    "Energy Efficiency": ["energy efficiency", "energy management", "energy audit",
                          "energy modelling", "energy modeling"],
    "Circular Economy": ["circular economy", "circularity", "resource efficiency"],
    "Waste Management": ["waste management", "zero waste", "recycling",
                         "waste reduction", "epr compliance"],
    "Water Stewardship": ["water stewardship", "water management", "water footprint",
                          "wastewater", "water conservation"],
    "Biodiversity": ["biodiversity", "nature positive", "ecosystem services",
                     "conservation", "natural capital"],
    "Life Cycle Assessment": ["life cycle assessment", "life-cycle assessment",
                              "lca", "product carbon footprint"],
    "Sustainable Supply Chain": ["sustainable supply chain", "supply chain sustainability",
                                 "responsible sourcing", "scope 3",
                                 "supplier engagement"],
    "Green Building": ["green building", "sustainable design", "built environment",
                       "sustainable construction"],
    "Air Quality": ["air quality", "emissions monitoring", "air pollution"],
    "EHS Compliance": ["ehs", "hse", "environmental compliance",
                       "health and safety", "environmental management system"],
    "Agriculture & Food Systems": ["sustainable agriculture", "regenerative agriculture",
                                   "food systems", "agroforestry"],
    "Sustainable Mobility": ["sustainable mobility", "electric vehicles", "e-mobility",
                             "ev charging"],
    # --- technology / general professional ---
    "Backend Development": ["backend development", "backend engineering", "back-end",
                            "server-side", "api development", "backend engineer",
                            "backend developer"],
    "Frontend Development": ["frontend development", "frontend engineering",
                             "front-end", "web development", "frontend engineer",
                             "frontend developer"],
    "Full-Stack Development": ["full stack", "full-stack", "full stack developer",
                               "full-stack developer", "full stack engineer"],
    "Mobile Development": ["mobile development", "android development",
                           "ios development", "app development",
                           "mobile developer", "android developer"],
    "Data Engineering": ["data engineering", "data pipelines", "etl development",
                         "data warehousing", "data engineer"],
    "Data Science": ["data science", "data analytics", "data analysis",
                     "statistical modelling", "statistical modeling",
                     "data scientist", "data analyst"],
    "Machine Learning": ["machine learning", "deep learning", "artificial intelligence",
                         "computer vision", "natural language processing", "mlops",
                         "ml engineer", "machine learning engineer"],
    "DevOps": ["devops", "site reliability", "platform engineering",
               "infrastructure as code", "devops engineer", "sre"],
    "Cloud Architecture": ["cloud architecture", "cloud engineering", "cloud migration",
                           "solutions architecture", "cloud engineer",
                           "solutions architect"],
    "Cybersecurity": ["cybersecurity", "cyber security", "information security",
                      "application security", "penetration testing",
                      "security engineer", "security analyst"],
    "Quality Assurance": ["quality assurance", "test automation", "qa engineering",
                          "qa engineer", "automation engineer"],
    "Algorithmic Trading": ["algorithmic trading", "algo trading", "quantitative trading",
                            "trading systems", "market data"],
    "Web Automation": ["web automation", "web scraping", "browser automation",
                       "process automation", "rpa"],
    "Product Management": ["product management", "product strategy", "product owner",
                           "product manager"],
    "Project Management": ["project management", "programme management",
                           "program management", "pmo"],
    "Business Analysis": ["business analysis", "business intelligence",
                          "requirements gathering"],
    "UI/UX Design": ["ui/ux", "user experience design", "ux research",
                     "interaction design", "product design"],
    "Digital Marketing": ["digital marketing", "performance marketing", "seo",
                          "content marketing", "growth marketing"],
    "Human Resources": ["human resources", "talent acquisition", "recruitment",
                        "people operations"],
    "Finance & Accounting": ["financial analysis", "financial reporting", "accounting",
                             "audit", "fp&a"],
    "Operations": ["operations management", "supply chain management", "logistics",
                   "procurement"],
    "Research": ["academic research", "research and development", "r&d"],
    "Teaching & Training": ["teaching", "training and development", "capacity building",
                            "curriculum"],
}

#: alias -> canonical focus area
_ALIASES = {}
for _canonical, _alias_list in FOCUS_DICTIONARY.items():
    _ALIASES[_canonical.lower()] = _canonical
    for _alias in _alias_list:
        _ALIASES[_alias] = _canonical

_LEFT = r"(?<![A-Za-z0-9&/-])"
_RIGHT = r"(?![A-Za-z0-9&/-])"
_PATTERNS = [
    (canonical, re.compile(_LEFT + re.escape(alias) + _RIGHT, re.IGNORECASE))
    for alias, canonical in sorted(_ALIASES.items(), key=lambda kv: -len(kv[0]))
]

#: Weight given to a hit depending on where in the resume it appears.
HEADLINE_WEIGHT = 2
BODY_WEIGHT = 1
#: A single passing mention in the body is not enough to call it a focus area.
MIN_SCORE = 2
MAX_FOCUS_AREAS = 6


def _headline_text(text, sections, experience=None):
    """The parts of a resume that signal what someone actually focuses on."""
    parts = [
        get_section(sections, "_preamble"),
        get_section(sections, "summary"),
    ]
    for entry in experience or []:
        parts.extend([entry.get("title", ""), entry.get("company", "")])

    # Job-title lines, which carry more signal than bullet points.
    experience_body = get_section(sections, "experience")
    parts.extend(list(iter_lines(experience_body))[:1])
    return "\n".join(part for part in parts if part)


def _count_hits(body):
    """Count focus-area hits in *body*, longest alias winning each span.

    Without this, the "accounting" alias of "Finance & Accounting" would also
    fire inside "carbon accounting" and invent a second focus area.
    """
    claimed = []
    hits = {}
    for canonical, pattern in _PATTERNS:   # longest alias first
        for match in pattern.finditer(body):
            start, end = match.span()
            if any(start < claimed_end and claimed_start < end
                   for claimed_start, claimed_end in claimed):
                continue
            claimed.append((start, end))
            hits[canonical] = hits.get(canonical, 0) + 1
    return hits


def extract_focus_area(text, sections=None, experience=None):
    """Return the candidate's focus areas, strongest first.

    Hits in the headline (name block, summary, job titles) count double, so a
    term used once in a bullet point does not outrank the stated specialism.
    """
    sections = sections or {}
    text = text or ""

    body_hits = _count_hits(text)
    headline_hits = _count_hits(_headline_text(text, sections, experience))

    scores = {}
    for canonical, count in body_hits.items():
        score = min(count, 3) * BODY_WEIGHT
        if canonical in headline_hits:
            score += HEADLINE_WEIGHT
        if score >= MIN_SCORE:
            scores[canonical] = score

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    return [name for name, _ in ranked[:MAX_FOCUS_AREAS]]
