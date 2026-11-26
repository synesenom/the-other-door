"""`core/salary.py`: the input for the salary question, its answer's validation and the years in a CV (#371)."""

import cv_read_utils
import pytest

from door.core import salary

CV = """# Jane Doe

**Phone:** +45 12 34 56 78 | **Email:** jane.doe@example.com | **Location:** Copenhagen

## Work Experience

### Senior Financial Controller | Acme Corp — 2021 - present

- Built the group controlling function.

### Financial Controller | Big Bank — 2018 - 2021

- Owned the IFRS reporting.

### Accountant | Example Retail — 2015 - 2018

- Ran accounts payable.

## Education

### BSc in Business Administration | Aarhus University — 2005 - 2010
"""

POSTING = {
    "title": "Senior Controller",
    "company": "Trustpilot",
    "location": "Copenhagen",
    "language": "en",
    "description": "About the role.\nWe offer a salary of DKK 60,000 per month.\nYou have 5+ years of experience.\nCake on Fridays.",
}


def _years(cv, **replace):
    return salary.years_of_experience(cv_read_utils.reading(cv, **replace), cv, now_year=2026)


def test_years_counts_dated_roles_and_ignores_education():
    assert _years(CV) == 11  # 2015 to now (2026); the degree's 2005 - 2010 is not work


def test_years_merges_overlapping_roles():
    assert _years("## Work Experience\n\n### A | X — 2015 - 2020\n\n### B | Y — 2018 - 2022\n") == 7


def test_years_without_dates_is_none():
    assert _years("## Work Experience\n\n### Controller | Acme\n") is None


def test_an_ongoing_role_runs_to_the_current_year():
    assert _years("## Work Experience\n\n### A | X — 2020 - present\n") == 6


def test_years_count_only_entries_of_experience_sections():
    cv = "## Publications\n\n### A | Journal — 2019 - 2021\n\n## Work Experience\n\n### B | Y — 2018 - 2020\n"
    assert _years(cv) == 2


def test_a_year_the_dates_do_not_contain_is_not_trusted():
    cv = "## Work Experience\n\n### A | X — 2015 - 2020\n"
    reading = cv_read_utils.reading(cv)
    reading["entries"][0]["start_year"] = 2010
    assert salary.years_of_experience(reading, cv, now_year=2026) is None


def test_an_entry_the_cv_does_not_have_is_ignored():
    cv = "## Work Experience\n\n### A | X — 2015 - 2020\n"
    reading = cv_read_utils.reading(cv)
    reading["entries"].append({**reading["entries"][0], "heading": "B | Y — 2001 - 2020"})
    assert salary.years_of_experience(reading, cv, now_year=2026) == 5


def test_a_dated_line_before_the_first_heading_or_under_a_skills_section_is_no_role():
    cv = "Freelance 2010 - present\n\n## Experience\n\n### Analyst — 2018 - 2020\n\n## Toolbox\n\n### Python — 2010 - 2024\n"
    assert _years(cv, sections=[{"heading": "Experience", "kind": "experience"}, {"heading": "Toolbox", "kind": "skills"}]) == 2


def _input(years=11, profile=None):
    profile = profile or {"name": "Jane Doe", "email": "jane@example.com", "location": "Copenhagen"}
    return salary.build_input(POSTING, profile, years)


def test_input_has_the_ad_the_country_and_the_counted_years():
    text = _input()
    assert "Senior Controller" in text and "Trustpilot" in text and "Copenhagen" in text
    assert "Denmark" in text and "dkk" in text.lower()
    assert "DKK 60,000 per month" in text
    assert "11 years" in text
    assert "Cake on Fridays" not in text
    assert "Jane" not in text and "jane@example.com" not in text


def test_input_says_when_the_years_cannot_be_counted():
    assert "not countable" in _input(None)


GOOD = {
    "found": True, "low": 55000, "high": 70000, "currency": "DKK", "period": "month", "gross": True,
    "position": "within", "basis": "11 years against the 5 the ad asks for",
    "sources": [{"title": "Lonstatistik", "url": "https://example.com/stats"}], "ad_salary": None,
}


def test_parse_accepts_a_valid_answer():
    parsed = salary.parse(GOOD)
    assert parsed["low"] == 55000 and parsed["high"] == 70000 and parsed["currency"] == "DKK"
    assert parsed["sources"] == [{"title": "Lonstatistik", "url": "https://example.com/stats"}]


def test_parse_keeps_a_one_line_why_and_drops_a_long_one():
    # the why sits in an info bubble beside the range: one short line, never the model's whole reasoning
    assert salary.parse(GOOD)["basis"] == "11 years against the 5 the ad asks for"
    rambling = "Market data for senior data scientists in Denmark is about DKK 655k-715k a year, " * 4
    assert salary.parse({**GOOD, "basis": rambling})["basis"] == ""


@pytest.mark.parametrize("change", [
    {"low": 80000},                      # low above high
    {"sources": []},                     # nothing cited
    {"sources": [{"title": "x", "url": "not a url"}]},
    {"currency": "kroner"},              # not a currency code
    {"period": "week"},
    {"low": 0},
    {"found": False},
])
def test_parse_refuses_what_cannot_be_trusted(change):
    assert salary.parse({**GOOD, **change}) is None


def test_parse_of_null_and_junk_is_none():
    assert salary.parse(None) is None and salary.parse("x") is None


def test_parse_keeps_only_valid_sources():
    sources = [{"title": "bad", "url": "ftp://x"}, {"title": "ok", "url": "https://ok.example/p"}]
    assert salary.parse({**GOOD, "sources": sources})["sources"] == [{"title": "ok", "url": "https://ok.example/p"}]
