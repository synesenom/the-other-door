"""`core/salary.py`: the input for the salary question, its answer's validation and the years in a CV (#371)."""

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


def test_years_counts_dated_roles_and_ignores_education():
    assert salary.years_of_experience(CV, now_year=2026) == 11  # 2015 to 2026


def test_years_merges_overlapping_roles():
    cv = "## Work Experience\n\n### A | X — 2015 - 2020\n\n### B | Y — 2018 - 2022\n"
    assert salary.years_of_experience(cv, now_year=2026) == 7


def test_years_without_dates_is_none():
    assert salary.years_of_experience("## Work Experience\n\n### Controller | Acme\n", now_year=2026) is None


def test_input_has_the_ad_the_country_and_the_counted_years():
    text = salary.build_input(POSTING, CV, {"name": "Jane Doe", "email": "jane@example.com", "location": "Copenhagen"},
                              now_year=2026)
    assert "Senior Controller" in text and "Trustpilot" in text and "Copenhagen" in text
    assert "Denmark" in text and "dkk" in text.lower()
    assert "DKK 60,000 per month" in text
    assert "11 years" in text
    assert "Cake on Fridays" not in text


def test_input_leaves_out_name_email_and_phone():
    text = salary.build_input(POSTING, CV, {"name": "Jane Doe", "email": "jane.doe@example.com", "location": "Copenhagen"},
                              now_year=2026)
    for private in ("Jane", "Doe", "jane.doe@example.com", "12 34 56 78"):
        assert private not in text
    assert "Senior Financial Controller" in text


GOOD = {
    "found": True, "low": 55000, "high": 70000, "currency": "DKK", "period": "month", "gross": True,
    "position": "within", "basis": "11 years against the 5 the ad asks for",
    "sources": [{"title": "Lonstatistik", "url": "https://example.com/stats"}], "ad_salary": None,
}


def test_parse_accepts_a_valid_answer():
    parsed = salary.parse(GOOD)
    assert parsed["low"] == 55000 and parsed["high"] == 70000 and parsed["currency"] == "DKK"
    assert parsed["sources"] == [{"title": "Lonstatistik", "url": "https://example.com/stats"}]


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
