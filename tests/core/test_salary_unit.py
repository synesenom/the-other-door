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


def _input(cv=CV, profile=None, **replace):
    profile = profile or {"name": "Jane Doe", "email": "jane@example.com", "location": "Copenhagen"}
    return salary.build_input(POSTING, cv, profile, cv_read_utils.reading(cv, **replace), now_year=2026)


def test_input_has_the_ad_the_country_and_the_counted_years():
    text = _input()
    assert "Senior Controller" in text and "Trustpilot" in text and "Copenhagen" in text
    assert "Denmark" in text and "dkk" in text.lower()
    assert "DKK 60,000 per month" in text
    assert "11 years" in text
    assert "Cake on Fridays" not in text


def test_input_leaves_out_name_email_and_phone():
    text = _input(profile={"name": "Jane Doe", "email": "jane.doe@example.com", "location": "Copenhagen"})
    for private in ("Jane", "Doe", "jane.doe@example.com", "12 34 56 78"):
        assert private not in text
    assert "Senior Financial Controller" in text


def test_the_cv_is_sent_from_its_first_section_so_the_header_never_goes():
    text = _input("# Ada L\n\n> Engineer at Zed | ada@example.org\n\n## Experience\n\n### Dev — 2020 - 2022\n- Built it\n")
    assert "Built it" in text and "Engineer at Zed" not in text and "# Ada" not in text


def test_a_contact_value_the_reading_found_goes_even_when_the_profile_has_none():
    cv = "# Ada\n\n**Tlf:** 99 88 77 66 | **Web:** ada-site.example\n\n## Experience\n\n### Dev at ada-site.example — 2020 - 2022\n"
    text = _input(cv, profile={}, contacts=[{"kind": "web", "label": "Web", "value": "ada-site.example"}], name="Ada")
    assert "ada-site.example" not in text and "Dev at" in text


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


def test_sections_that_are_not_about_the_work_never_go_out_references_and_contacts_included():
    cv = ("# Ada\n\n## Summary\n\nCall me.\n\n## Experience\n\n### Dev — 2020 - 2022\n- Built it\n\n"
          "## References\n\nBo Berg, 00 00 00 99\n\n## Contact\n\nada@example.org\n\n## Skills\n\nPython\n")
    kinds = ["summary", "experience", "other", "other", "skills"]
    sections = [{"heading": h, "kind": k} for h, k in zip(["Summary", "Experience", "References", "Contact", "Skills"], kinds)]
    text = _input(cv, profile={}, sections=sections)
    assert "Built it" in text and "Python" in text
    for gone in ("Bo Berg", "ada@example.org", "Call me"):
        assert gone not in text


def test_a_contact_value_is_removed_however_the_cv_spaces_it():
    cv = "# Ada\n\n## Experience\n\n### Dev — 2020 - 2022\n- Reach me on +45  00 00\n  00 00 any time\n"
    text = _input(cv, profile={}, contacts=[{"kind": "phone", "label": None, "value": "+45 00 00 00 00"}])
    assert "00 00" not in text and "any time" in text
