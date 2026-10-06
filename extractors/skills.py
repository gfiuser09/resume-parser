"""Skill extraction.

Two complementary strategies are used:

1. Section parsing - whatever the candidate listed under a "Skills" heading is
   split on the usual delimiters and kept as-is. This catches niche or
   company-specific skills that no dictionary could know about.
2. Dictionary matching - a curated keyword list is matched against the whole
   document, so skills mentioned only inside job bullet points are found too.

Results are normalised to a canonical spelling (nodejs -> Node.js) and
de-duplicated case-insensitively.
"""

import re

from utils.text_utils import clean_line, get_section, iter_lines

#: canonical skill name -> extra aliases/spellings that map onto it
SKILL_DICTIONARY = {
    # --- languages ---
    "Python": ["python", "python3"],
    "Java": ["java"],
    "JavaScript": ["javascript", "java script", "es6", "ecmascript"],
    "TypeScript": ["typescript"],
    "C": [],
    "C++": ["c++", "cpp", "c plus plus"],
    "C#": ["c#", "csharp", "c sharp"],
    "Go": ["golang"],
    "Rust": ["rust"],
    "Ruby": ["ruby"],
    "PHP": ["php"],
    "Swift": ["swift"],
    "Kotlin": ["kotlin"],
    "Scala": ["scala"],
    "Perl": ["perl"],
    "R": [],
    "MATLAB": ["matlab"],
    "Dart": ["dart"],
    "Objective-C": ["objective-c", "objective c"],
    "Shell Scripting": ["bash", "shell scripting", "shell script", "zsh", "powershell"],
    "SQL": ["sql"],
    "HTML": ["html", "html5"],
    "CSS": ["css", "css3"],
    "SASS": ["sass", "scss"],
    "Solidity": ["solidity"],
    # --- frontend ---
    "React": ["react", "react.js", "reactjs"],
    "Next.js": ["next.js", "nextjs"],
    "Vue.js": ["vue", "vue.js", "vuejs"],
    "Angular": ["angular", "angularjs", "angular.js"],
    "Svelte": ["svelte", "sveltekit"],
    "jQuery": ["jquery"],
    "Redux": ["redux"],
    "Tailwind CSS": ["tailwind", "tailwind css", "tailwindcss"],
    "Bootstrap": ["bootstrap"],
    "Material UI": ["material ui", "material-ui", "mui"],
    "Webpack": ["webpack"],
    "Vite": ["vite"],
    "React Native": ["react native", "react-native"],
    "Flutter": ["flutter"],
    "Android": ["android", "android sdk"],
    "iOS": ["ios"],
    # --- backend / frameworks ---
    "Node.js": ["node", "node.js", "nodejs"],
    "Express.js": ["express", "express.js", "expressjs"],
    "NestJS": ["nestjs", "nest.js"],
    "Django": ["django"],
    "Flask": ["flask"],
    "FastAPI": ["fastapi", "fast api"],
    "Spring Boot": ["spring", "spring boot", "springboot"],
    "Laravel": ["laravel"],
    "Ruby on Rails": ["rails", "ruby on rails"],
    "ASP.NET": ["asp.net", "aspnet"],
    ".NET": [".net", "dotnet", "dot net"],
    "GraphQL": ["graphql"],
    "REST APIs": ["rest", "rest api", "rest apis", "restful", "restful api",
                  "restful apis"],
    "gRPC": ["grpc"],
    "WebSockets": ["websocket", "websockets", "socket.io", "socketio"],
    "Microservices": ["microservice", "microservices"],
    # --- data stores ---
    "PostgreSQL": ["postgresql", "postgres", "psql"],
    "MySQL": ["mysql"],
    "SQLite": ["sqlite"],
    "MongoDB": ["mongodb", "mongo"],
    "Redis": ["redis"],
    "Elasticsearch": ["elasticsearch", "elastic search"],
    "Cassandra": ["cassandra"],
    "DynamoDB": ["dynamodb"],
    "Firebase": ["firebase", "firestore"],
    "Supabase": ["supabase"],
    "Oracle": ["oracle db", "oracle database"],
    "Microsoft SQL Server": ["sql server", "mssql", "ms sql"],
    "Snowflake": ["snowflake"],
    "BigQuery": ["bigquery", "big query"],
    # --- cloud / devops ---
    "AWS": ["aws", "amazon web services"],
    "Azure": ["azure", "microsoft azure"],
    "Google Cloud": ["gcp", "google cloud", "google cloud platform"],
    "Docker": ["docker"],
    "Kubernetes": ["kubernetes", "k8s"],
    "Terraform": ["terraform"],
    "Ansible": ["ansible"],
    "Jenkins": ["jenkins"],
    "CI/CD": ["ci/cd", "cicd", "continuous integration", "continuous deployment"],
    "GitHub Actions": ["github actions"],
    "GitLab CI": ["gitlab ci"],
    "Nginx": ["nginx"],
    "Apache": ["apache", "apache2", "httpd"],
    "Linux": ["linux", "ubuntu", "debian", "centos", "rhel"],
    "Git": ["git", "github", "gitlab", "bitbucket", "version control"],
    "Prometheus": ["prometheus"],
    "Grafana": ["grafana"],
    "Kafka": ["kafka", "apache kafka"],
    "RabbitMQ": ["rabbitmq"],
    "Celery": ["celery"],
    "Serverless": ["serverless", "aws lambda"],
    # --- data / ML ---
    "Machine Learning": ["machine learning"],
    "Deep Learning": ["deep learning"],
    "NLP": ["nlp", "natural language processing"],
    "Computer Vision": ["computer vision", "opencv"],
    "TensorFlow": ["tensorflow"],
    "PyTorch": ["pytorch"],
    "Keras": ["keras"],
    "scikit-learn": ["scikit-learn", "sklearn", "scikit learn"],
    "Pandas": ["pandas"],
    "NumPy": ["numpy"],
    "Matplotlib": ["matplotlib"],
    "Spark": ["apache spark", "pyspark"],
    "Hadoop": ["hadoop"],
    "Airflow": ["airflow", "apache airflow"],
    "Tableau": ["tableau"],
    "Power BI": ["power bi", "powerbi"],
    "Excel": ["microsoft excel", "ms excel"],
    "Data Analysis": ["data analysis", "data analytics"],
    "ETL": ["etl"],
    "LLMs": ["llm", "llms", "large language models", "openai", "langchain"],
    # --- testing / practices ---
    "Unit Testing": ["unit testing", "unit tests"],
    "Pytest": ["pytest"],
    "Jest": ["jest"],
    "Selenium": ["selenium"],
    "Cypress": ["cypress"],
    "JUnit": ["junit"],
    "TDD": ["tdd", "test driven development", "test-driven development"],
    "Agile": ["agile", "scrum", "kanban"],
    "JIRA": ["jira"],
    "System Design": ["system design", "software architecture"],
    "Object-Oriented Programming": ["oop", "object oriented programming",
                                    "object-oriented programming"],
    "Data Structures": ["data structures"],
    "Algorithms": ["algorithms"],
    # --- design / product / soft skills ---
    "Figma": ["figma"],
    "Adobe Photoshop": ["photoshop", "adobe photoshop"],
    "UI/UX Design": ["ui/ux", "ux design", "ui design", "user experience"],
    "WordPress": ["wordpress"],
    "SEO": ["seo", "search engine optimization"],
    "Project Management": ["project management"],
    "Communication": ["communication", "communication skills"],
    "Leadership": ["leadership", "team leadership"],
    "Teamwork": ["teamwork", "collaboration"],
    "Problem Solving": ["problem solving", "problem-solving"],
}

#: Short/ambiguous names that are only trusted inside an explicit skills section.
AMBIGUOUS = {"C", "R", "Go", "Dart", "Swift", "Rust", "Apache", "Oracle", "Excel",
             "Android", "iOS", "Spark", "Jest", "Vite", "Keras"}

#: alias (lowercase) -> canonical name
_ALIASES = {}
for _canonical, _alias_list in SKILL_DICTIONARY.items():
    _ALIASES[_canonical.lower()] = _canonical
    for _alias in _alias_list:
        _ALIASES[_alias] = _canonical

# Boundaries that tolerate characters which are part of skill names (c++, c#,
# .net, node.js) instead of plain \b, which would break on them.
_LEFT = r"(?<![A-Za-z0-9+#])"
_RIGHT = r"(?![A-Za-z0-9#]|\+\+)"
_PATTERNS = [
    (canonical, re.compile(_LEFT + re.escape(alias) + _RIGHT, re.IGNORECASE))
    for alias, canonical in sorted(_ALIASES.items(), key=lambda kv: -len(kv[0]))
]

_DELIMITERS = re.compile(
    r"[,;|\t]"                      # comma / semicolon / pipe / tab
    r"|[•·▪◦]"  # bullet glyphs used as inline separators
    r"|\s{3,}"                      # column gaps left by PDF/OCR extraction
    r"|\s[-–—]\s"         # " - " / en dash / em dash
)
#: A group label at the start of a skills line: "Languages: Python, Go".
#: OCR frequently drops the colon, so it is optional after a known label word.
_GROUP_LABELS = (
    "languages?|frameworks?|libraries|librar(?:y|ies)|tools?|technolog(?:y|ies)"
    r"|databases?|platforms?|backend|frontend|front-end|back-end|full[- ]stack"
    r"|cloud|devops|testing|tooling|others?|miscellaneous|misc|soft skills?"
    r"|technical|programming|scripting|concepts?|methodolog(?:y|ies)"
)
_LABEL = re.compile(
    r"^(?:[A-Za-z][A-Za-z /&+#.-]{0,40}:\s*"      # any "Label:" prefix
    r"|(?:" + _GROUP_LABELS + r")\s+(?=[A-Za-z]))",  # or a known label, no colon
    re.IGNORECASE,
)

MAX_SKILL_WORDS = 5
MAX_SKILL_CHARS = 40


def _contains_known_skill(token):
    """True when *token* has a dictionary skill inside it.

    Such a token is a run-on - OCR dropping the commas in
    "Kubernetes, PostgreSQL, Redis" yields one long token. The dictionary sweep
    picks up each skill individually, so the run-on itself is dropped.
    """
    return any(
        pattern.search(token)
        for canonical, pattern in _PATTERNS
        if canonical not in AMBIGUOUS
    )


def canonicalize(token):
    """Map a raw token onto its canonical skill name, or ``None`` if unusable."""
    token = clean_line(token).strip(" .")
    if not token:
        return None

    key = re.sub(r"\s+", " ", token.lower()).strip(" .")
    if key in _ALIASES:
        return _ALIASES[key]

    # Keep unknown-but-plausible tokens so niche tools are not lost.
    if len(token) < 2 or len(token) > MAX_SKILL_CHARS:
        return None
    if len(token.split()) > MAX_SKILL_WORDS:
        return None
    if not re.search(r"[A-Za-z]", token):
        return None
    if re.search(r"\d{4}", token) or "@" in token:
        return None
    return token


def _tokens_from_section(section_text):
    """Yield candidate skill tokens from the body of a skills section."""
    for line in iter_lines(section_text):
        line = clean_line(line)
        if not line:
            continue
        # Drop a leading group label, e.g. "Languages: Python, Java".
        line = _LABEL.sub("", line)
        for token in _DELIMITERS.split(line):
            token = (token or "").strip()
            if token:
                yield token


def extract_skills(text, sections=None):
    """Return the skills found in *text* as a sorted list of strings.

    *sections* is the mapping produced by :func:`utils.text_utils.split_sections`.
    Passing it lets explicitly listed skills take priority over keyword hits.
    """
    sections = sections or {}
    found = {}  # lowercase key -> display name

    def add(name):
        if name and name.lower() not in found:
            found[name.lower()] = name

    skills_section = get_section(sections, "skills")
    if skills_section:
        for token in _tokens_from_section(skills_section):
            name = canonicalize(token)
            if name is None:
                continue
            is_known = name.lower() in _ALIASES
            if not is_known and _contains_known_skill(name):
                continue  # run-on of known skills; the sweep below covers them
            add(name)

    # Dictionary sweep over the whole document.
    haystack = text or ""
    for canonical, pattern in _PATTERNS:
        if canonical in AMBIGUOUS and canonical.lower() not in found:
            continue  # only accepted from an explicit skills section
        if pattern.search(haystack):
            add(canonical)

    return sorted(found.values(), key=str.lower)
