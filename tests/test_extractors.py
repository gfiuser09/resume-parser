"""Unit tests for the extraction layer (no Flask, no files involved)."""

import pytest

from extractors import (
    EMPTY_RESULT,
    ExtractionEngine,
    RuleBasedEngine,
    extract_resume_data,
    get_engine,
    register_engine,
)
from extractors.education import extract_education
from extractors.experience import extract_experience
from extractors.resume_extractor import extract_email, extract_name
from extractors.skills import canonicalize, extract_skills
from utils.text_utils import normalize_text, split_sections


def analyse(text):
    normalised = normalize_text(text)
    return normalised, split_sections(normalised)


# --- email -----------------------------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("Reach me at jane.doe@example.co.uk.", "jane.doe@example.co.uk"),
        ("Email: JOHN+hire@sub.domain.io | Phone", "JOHN+hire@sub.domain.io"),
        ("no address here", ""),
        ("mail me (a.b-c_d@test-mail.org)", "a.b-c_d@test-mail.org"),
    ],
)
def test_extract_email(text, expected):
    assert extract_email(text) == expected


# --- name ------------------------------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("Priya Sharma\npriya@example.com", "Priya Sharma"),
        ("RAHUL KUMAR SINGH\nSoftware Engineer", "Rahul Kumar Singh"),
        ("Name: Aisha Khan\nSenior Analyst", "Aisha Khan"),
        ("CURRICULUM VITAE\nMaria Garcia\nmaria@x.com", "Maria Garcia"),
        ("John A. Doe\njohn@x.com", "John A. Doe"),
    ],
)
def test_extract_name(text, expected):
    normalised, sections = analyse(text)
    assert extract_name(normalised, sections, extract_email(normalised)) == expected


def test_name_falls_back_to_email_local_part():
    normalised, sections = analyse("Experienced engineer\nravi.verma@example.com")
    assert extract_name(normalised, sections, "ravi.verma@example.com") == "Ravi Verma"


def test_name_is_empty_when_nothing_looks_like_one():
    normalised, sections = analyse("SUMMARY\nTen years of backend work.")
    assert extract_name(normalised, sections, "") == ""


# --- skills ----------------------------------------------------------------

def test_skills_from_section_and_body():
    normalised, sections = analyse(
        "SKILLS\nLanguages: python, nodejs, c++\nTools: Internal Billing DSL\n\n"
        "EXPERIENCE\nShipped services on kubernetes and postgres.\n"
    )
    skills = extract_skills(normalised, sections)
    assert "Python" in skills                 # canonical casing
    assert "Node.js" in skills                # alias normalised
    assert "C++" in skills                    # punctuation-bearing name
    assert "Internal Billing DSL" in skills   # unknown but plausible, kept
    assert "Kubernetes" in skills             # found in a bullet, not the section
    assert "PostgreSQL" in skills


def test_skills_are_deduplicated_and_sorted():
    normalised, sections = analyse("SKILLS\nPython, python3, PYTHON, Django\n")
    assert extract_skills(normalised, sections) == ["Django", "Python"]


def test_javascript_does_not_match_java():
    normalised, sections = analyse("EXPERIENCE\nBuilt UIs in JavaScript.\n")
    skills = extract_skills(normalised, sections)
    assert "JavaScript" in skills
    assert "Java" not in skills


def test_ambiguous_skills_need_an_explicit_section():
    body, body_sections = analyse("EXPERIENCE\nI like to go for a run.\n")
    assert "Go" not in extract_skills(body, body_sections)

    listed, listed_sections = analyse("SKILLS\nGo, Rust\n")
    assert {"Go", "Rust"} <= set(extract_skills(listed, listed_sections))


@pytest.mark.parametrize(
    "token,expected",
    [
        ("  react.js ", "React"),
        ("GOLANG", "Go"),
        ("2015 - 2019", None),
        ("a@b.com", None),
        ("x", None),
        ("a very long phrase that is clearly not a skill at all", None),
    ],
)
def test_canonicalize(token, expected):
    assert canonicalize(token) == expected


# --- education -------------------------------------------------------------

def test_education_single_line_entries():
    normalised, sections = analyse(
        "EDUCATION\nB.Tech in Computer Science, XYZ University, 2015 - 2019\n"
        "CGPA: 8.7/10\n\nHigher Secondary, ABC Public School, 2015\n"
    )
    entries = extract_education(normalised, sections)
    assert len(entries) == 2
    assert entries[0] == {
        "degree": "B.Tech in Computer Science",
        "institution": "XYZ University",
        "year": "2015 - 2019",
        "details": "CGPA: 8.7/10",
    }
    assert entries[1]["institution"] == "ABC Public School"


def test_education_multi_line_entries():
    normalised, sections = analyse(
        "EDUCATION\nMaster of Science in Data Science\nStanford University\n2020 - 2022\n"
        "Bachelor of Engineering\nPune Institute of Technology\n2014 - 2018\n"
    )
    entries = extract_education(normalised, sections)
    assert [entry["institution"] for entry in entries] == [
        "Stanford University", "Pune Institute of Technology",
    ]


def test_education_without_a_section_header():
    normalised, sections = analyse(
        "SUMMARY\nEngineer who completed a B.Sc from Delhi University in 2017.\n"
    )
    entries = extract_education(normalised, sections)
    assert entries[0]["institution"] == "Delhi University"
    assert entries[0]["year"] == "2017"


def test_education_is_empty_when_absent():
    normalised, sections = analyse("SKILLS\nPython\n")
    assert extract_education(normalised, sections) == []


# --- experience ------------------------------------------------------------

def test_experience_pipe_separated_header():
    normalised, sections = analyse(
        "WORK EXPERIENCE\n"
        "Senior Backend Engineer | Acme Technologies Pvt Ltd | Jan 2020 - Present\n"
        "- Designed REST APIs.\n- Led a team of 4 engineers.\n"
    )
    entry = extract_experience(normalised, sections)[0]
    assert entry["title"] == "Senior Backend Engineer"
    assert entry["company"] == "Acme Technologies Pvt Ltd"
    assert entry["duration"] == "Jan 2020 - Present"
    assert entry["location"] == ""
    assert "Designed REST APIs." in entry["description"]


def test_experience_stacked_lines_and_bare_date_line():
    normalised, sections = analyse(
        "PROFESSIONAL EXPERIENCE\nData Analyst\nInitech Systems, Remote\n"
        "03/2021 - 08/2023\nAnalysed customer churn with SQL and Tableau.\n"
        "Marketing Intern\nBrightMedia Group\n2019 - 2020\n"
    )
    entries = extract_experience(normalised, sections)
    assert len(entries) == 2
    assert entries[0]["title"] == "Data Analyst"
    assert entries[0]["company"] == "Initech Systems"
    assert entries[0]["duration"] == "03/2021 - 08/2023"
    assert "churn" in entries[0]["description"]
    assert entries[1]["title"] == "Marketing Intern"
    assert entries[1]["duration"] == "2019 - 2020"


def test_experience_at_separator():
    normalised, sections = analyse(
        "EXPERIENCE\nSoftware Developer at Globex Solutions\nJune 2017 - Dec 2019\n"
    )
    entry = extract_experience(normalised, sections)[0]
    assert entry["title"] == "Software Developer"
    assert entry["company"] == "Globex Solutions"


def test_experience_is_empty_when_absent():
    normalised, sections = analyse("EDUCATION\nB.Tech, XYZ University, 2019\n")
    assert extract_experience(normalised, sections) == []


# --- engine plumbing -------------------------------------------------------

def test_default_engine_is_rule_based():
    assert isinstance(get_engine(), RuleBasedEngine)


def test_result_shape_is_stable_for_empty_input():
    assert extract_resume_data("") == EMPTY_RESULT
    assert all(value in ("", []) for value in EMPTY_RESULT.values())


def test_a_custom_engine_can_replace_the_default():
    class StubEngine(ExtractionEngine):
        name = "stub"

        def extract(self, text):
            return dict(EMPTY_RESULT, candidate_name="Stub")

    register_engine(StubEngine)
    assert isinstance(get_engine("stub"), StubEngine)
    assert extract_resume_data("x", engine="stub")["candidate_name"] == "Stub"
    assert extract_resume_data("x", engine=StubEngine())["candidate_name"] == "Stub"


# --- regressions found on real-world resumes -------------------------------

def test_name_shares_a_line_with_a_phone_number():
    normalised, sections = analyse(
        "Uttam Kumar 9065880852\nB.Tech(2027)\nEmail id-someone5050@gmail.com\n"
    )
    assert extract_name(normalised, sections, "") == "Uttam Kumar"


def test_contact_label_is_not_part_of_the_email():
    assert extract_email("Email id-someone5050@gmail.com | GitHub") == \
        "someone5050@gmail.com"
    assert extract_email("E-mail id-first.last@corp.co.in") == "first.last@corp.co.in"


def test_a_hyphenated_local_part_is_left_alone():
    # "id-cards@" is a plausible real address, so only "<mail word> id-" is stripped.
    assert extract_email("Contact: id-cards@company.com") == "id-cards@company.com"


def test_month_span_duration_and_company_without_a_keyword():
    normalised, sections = analyse(
        "Experience\n"
        "Backend Developer Intern - Limnox Technologies March-April(2025)\n"
        "SKILLS USED: PYTHON (DJANGO), DJANGO REST FRAMEWORK (DRF), MYSQL\n"
        "Engineered and maintained RESTful APIs using Django and DRF.\n"
        "Backend Developer Intern - CreditXchange.AI 15 July- 15 Oct(2025)\n"
        "Partnered with trading researchers to ship analytical dashboards.\n"
    )
    entries = extract_experience(normalised, sections)
    assert len(entries) == 2

    assert entries[0]["title"] == "Backend Developer Intern"
    assert entries[0]["company"] == "Limnox Technologies"
    assert entries[0]["duration"] == "March - April 2025"
    # A labelled line is description content, not a header to be carved up.
    assert entries[0]["location"] == ""

    assert entries[1]["company"] == "CreditXchange.AI"
    assert entries[1]["duration"] == "15 July - 15 Oct 2025"


def test_education_ignores_personal_details():
    normalised, sections = analyse(
        "Computer Science & Engineering (IIOT) B.Tech(2027)\n"
        "GURU GOBIND SINGH INDRAPRASTHA UNIVERSITY, Gender: Male\n"
        "NEW DELHI DOB:08/02/2003\n\nSUMMARY\nBackend developer.\n"
    )
    entry = extract_education(normalised, sections)[0]
    assert entry["degree"] == "Computer Science & Engineering (IIOT) B.Tech"
    assert entry["institution"] == "GURU GOBIND SINGH INDRAPRASTHA UNIVERSITY"
    assert entry["year"] == "2027"
    assert "Gender" not in entry["details"]


# --- OCR artefacts ---------------------------------------------------------

def test_email_with_ocr_inserted_spaces():
    assert extract_email("john.doe @example.com | +91 98765") == "john.doe@example.com"
    assert extract_email("jane @ corp . com") == "jane@corp.com"


def test_skills_survive_ocr_dropping_colons_and_commas():
    # Tesseract commonly loses the ":" after a group label and the commas
    # between items, leaving run-on lines.
    normalised, sections = analyse(
        "TECHNICAL SKILLS\n"
        "Languages Python, JavaScript Go SQL\n"
        "Tools Docker, Kubernetes PostgreSQL Redis Git\n"
    )
    skills = extract_skills(normalised, sections)
    assert {"Python", "JavaScript", "SQL", "Docker", "Kubernetes",
            "PostgreSQL", "Redis", "Git"} <= set(skills)
    # The run-on tokens themselves must not leak through as "skills".
    assert not [s for s in skills if len(s.split()) > 2]
    assert "Languages Python" not in skills
    assert "Tools Docker" not in skills


def test_group_label_with_a_colon_still_works():
    normalised, sections = analyse("SKILLS\nLanguages: Python, Go\n")
    assert extract_skills(normalised, sections) == ["Go", "Python"]


def test_unknown_multiword_skills_are_still_kept():
    normalised, sections = analyse("SKILLS\nInternal Billing DSL, Figma\n")
    assert "Internal Billing DSL" in extract_skills(normalised, sections)
