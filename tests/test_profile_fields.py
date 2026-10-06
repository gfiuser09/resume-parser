"""Tests for the profile fields: phone, LinkedIn, location, role, bio,
focus areas and sustainability certifications."""

import pytest

from extractors import extract_resume_data
from extractors.certifications import extract_sustainability_certifications
from extractors.contact import (
    extract_current_location,
    extract_linkedin_url,
    extract_phone,
)
from extractors.experience import extract_experience
from extractors.focus import extract_focus_area
from extractors.resume_extractor import (
    extract_bio,
    extract_current_company,
    extract_current_job_title,
)
from utils.text_utils import normalize_text, split_sections


def analyse(text):
    normalised = normalize_text(text)
    return normalised, split_sections(normalised)


ESG_RESUME = """PRIYA SHARMA
Sustainability Lead
priya.sharma@greenaudit.io | +91 98200 11223 | linkedin.com/in/priya-sharma-esg
Mumbai, India

SUMMARY
Sustainability professional with 7 years in corporate carbon accounting and ESG
reporting. Led net zero roadmaps for listed manufacturers.

CERTIFICATIONS
LEED Green Associate, GRI Certified Sustainability Reporting
ISO 14001 Lead Auditor
AWS Certified Cloud Practitioner

WORK EXPERIENCE
ESG Reporting Lead | GreenAudit Solutions Pvt Ltd | Mar 2021 - Present
- Produced BRSR and GRI-aligned disclosures for 12 listed clients.

Environment Analyst, Terra Consulting, Pune, Jun 2017 - Feb 2021
- Delivered life cycle assessment studies.

EDUCATION
M.Sc in Environmental Science, University of Mumbai, 2015 - 2017
"""


# --- phone ------------------------------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("Uttam Kumar 9065880852", "9065880852"),
        ("Contact +91 9065880852 | GitHub", "+91 9065880852"),
        ("Phone: 555-1234", "555-1234"),
        ("Mobile +1 (555) 123-4567", "+1 (555) 123-4567"),
        ("no number at all", ""),
    ],
)
def test_extract_phone(text, expected):
    normalised, sections = analyse(text)
    assert extract_phone(normalised, sections) == expected


@pytest.mark.parametrize(
    "text",
    [
        "EDUCATION\nB.Tech, XYZ University, 2015 - 2019\n",   # a year range
        "EXPERIENCE\nWorked there Jan 2020 - Present\n",      # a date range
        "EDUCATION\nCGPA: 8.7/10\n",                          # a grade
        "Served 2M requests/day at 40% lower latency\n",      # metrics
    ],
)
def test_numbers_that_are_not_phone_numbers(text):
    normalised, sections = analyse(text)
    assert extract_phone(normalised, sections) == ""


# --- LinkedIn ---------------------------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("linkedin.com/in/johndoe", "https://www.linkedin.com/in/johndoe"),
        ("https://www.linkedin.com/in/uttam-kumar-123/",
         "https://www.linkedin.com/in/uttam-kumar-123"),
        ("profile: in.linkedin.com/in/jane-roe",
         "https://www.linkedin.com/in/jane-roe"),
        ("linkedin.com/ in/ john-doe", "https://www.linkedin.com/in/john-doe"),
        ("LinkedIn", ""),          # the bare word carries no URL
        ("github.com/someone", ""),
    ],
)
def test_extract_linkedin_url(text, expected):
    assert extract_linkedin_url(text) == expected


# --- location ---------------------------------------------------------------

def test_location_from_the_header_block():
    normalised, sections = analyse("JOHN A. DOE\njohn@x.com\nBangalore, India\n")
    assert extract_current_location(normalised, sections, [], "John A. Doe") == \
        "Bangalore, India"


def test_location_survives_an_inline_personal_detail():
    normalised, sections = analyse("Uttam Kumar 9065880852\nNEW DELHI DOB:08/02/2003\n")
    assert extract_current_location(normalised, sections, [], "Uttam Kumar") == \
        "New Delhi"


def test_the_candidates_name_is_not_read_as_a_location():
    normalised, sections = analyse("Maria Garcia\nmaria@x.com\n")
    assert extract_current_location(normalised, sections, [], "Maria Garcia") == ""


def test_current_job_location_outranks_an_older_one():
    experience = [
        {"title": "Lead", "company": "A", "duration": "2021 - Present",
         "location": "Berlin"},
        {"title": "Dev", "company": "B", "duration": "2018 - 2021",
         "location": "Pune"},
    ]
    normalised, sections = analyse("Someone\nMumbai, India\n")
    assert extract_current_location(
        normalised, sections, experience, "Someone", preferred="Berlin"
    ) == "Berlin"


def test_header_outranks_a_previous_employers_city():
    # The current job has no location, so the header wins over the old job's.
    experience = [
        {"title": "Lead", "company": "A", "duration": "2021 - Present", "location": ""},
        {"title": "Dev", "company": "B", "duration": "2018 - 2021", "location": "Pune"},
    ]
    normalised, sections = analyse("Someone\nMumbai, India\n")
    assert extract_current_location(
        normalised, sections, experience, "Someone"
    ) == "Mumbai, India"


# --- bio and current role ---------------------------------------------------

def test_bio_is_the_summary_as_one_paragraph():
    normalised, sections = analyse(ESG_RESUME)
    bio = extract_bio(normalised, sections)
    assert bio.startswith("Sustainability professional with 7 years")
    assert "\n" not in bio          # PDF line wrapping is collapsed
    assert "CERTIFICATIONS" not in bio


def test_bio_is_empty_without_a_summary_section():
    normalised, sections = analyse("SKILLS\nPython\n")
    assert extract_bio(normalised, sections) == ""


def test_current_role_comes_from_the_present_job():
    normalised, sections = analyse(ESG_RESUME)
    experience = extract_experience(normalised, sections)
    assert extract_current_job_title(normalised, sections, experience) == \
        "ESG Reporting Lead"
    assert extract_current_company(experience) == "GreenAudit Solutions Pvt Ltd"


def test_current_role_falls_back_to_the_header_headline():
    normalised, sections = analyse("Priya Sharma\nSustainability Lead\npriya@x.io\n")
    assert extract_current_job_title(normalised, sections, []) == "Sustainability Lead"
    assert extract_current_company([]) == ""


def test_present_job_wins_over_document_order():
    experience = [
        {"title": "Consultant", "company": "Old Co", "duration": "2015 - 2018"},
        {"title": "Head of ESG", "company": "New Co", "duration": "2019 - Present"},
    ]
    assert extract_current_job_title("", {}, experience) == "Head of ESG"
    assert extract_current_company(experience) == "New Co"


# --- focus areas ------------------------------------------------------------

def test_focus_areas_are_ranked_and_domain_specific():
    normalised, sections = analyse(ESG_RESUME)
    experience = extract_experience(normalised, sections)
    areas = extract_focus_area(normalised, sections, experience)
    assert "ESG Reporting" in areas
    assert "Carbon Accounting" in areas
    # "accounting" must not also match the generic finance area inside
    # "carbon accounting".
    assert "Finance & Accounting" not in areas


def test_focus_areas_cover_non_sustainability_resumes():
    normalised, sections = analyse(
        "Uttam Kumar\nSUMMARY\nBackend Developer with experience in web automation\n"
        "and algorithmic trading.\nEXPERIENCE\nBackend Developer - Acme Ltd\n"
        "- Built trading systems and web scraping pipelines.\n"
    )
    areas = extract_focus_area(normalised, sections,
                               extract_experience(normalised, sections))
    assert {"Algorithmic Trading", "Web Automation"} <= set(areas)


def test_a_single_passing_mention_is_not_a_focus_area():
    normalised, sections = analyse(
        "EXPERIENCE\nDeveloper at Acme\n- Attended one talk about biodiversity.\n"
    )
    assert "Biodiversity" not in extract_focus_area(normalised, sections, [])


# --- sustainability certifications ------------------------------------------

def test_sustainability_certifications_are_recognised_and_filtered():
    normalised, sections = analyse(ESG_RESUME)
    certifications = extract_sustainability_certifications(normalised, sections)
    assert "LEED Green Associate" in certifications
    assert "GRI Certified" in certifications
    assert "ISO 14001 Lead Auditor" in certifications
    # Non-sustainability credentials are out of scope for this field.
    assert not any("AWS" in item for item in certifications)


def test_unknown_credentials_need_both_a_green_term_and_a_credential_word():
    normalised, sections = analyse(
        "CERTIFICATIONS\nCorporate Water Stewardship Masterclass\n"
        "Certified Scrum Master\n"
    )
    certifications = extract_sustainability_certifications(normalised, sections)
    assert certifications == ["Corporate Water Stewardship Masterclass"]


def test_prose_mentioning_environment_is_not_a_certification():
    normalised, sections = analyse(
        "ACHIEVEMENTS\nThrived in agile development environments and green teams.\n"
    )
    assert extract_sustainability_certifications(normalised, sections) == []


def test_no_certifications_section_yields_an_empty_list():
    normalised, sections = analyse("SKILLS\nPython, Django\n")
    assert extract_sustainability_certifications(normalised, sections) == []


# --- end to end -------------------------------------------------------------

def test_every_profile_field_is_populated_for_a_full_resume():
    data = extract_resume_data(ESG_RESUME)
    assert data["candidate_name"] == "Priya Sharma"
    assert data["email"] == "priya.sharma@greenaudit.io"
    assert data["phone"] == "+91 98200 11223"
    assert data["linkedin_url"] == "https://www.linkedin.com/in/priya-sharma-esg"
    assert data["current_location"] == "Mumbai, India"
    assert data["current_job_title"] == "ESG Reporting Lead"
    assert data["current_company"] == "GreenAudit Solutions Pvt Ltd"
    assert data["bio"].startswith("Sustainability professional")
    assert data["focus_area"]
    assert data["sustainability_certifications"]
    assert data["education"] and data["experience"]


def test_missing_fields_come_back_empty_not_absent():
    data = extract_resume_data("Just a line of text with no resume structure.")
    for field in ["phone", "linkedin_url", "current_location", "current_job_title",
                  "current_company", "bio"]:
        assert data[field] == "", field
    for field in ["focus_area", "sustainability_certifications"]:
        assert data[field] == [], field
