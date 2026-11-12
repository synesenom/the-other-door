"""Unit tests for the SmartRecruiters public postings API's pure helpers."""

import pytest

from door.scrapers.feeds import smartrecruiters


@pytest.mark.parametrize("entry, company", [
    ("interikeagroup", "interikeagroup"),
    (" NCS3 ", "NCS3"),
    ("https://jobs.smartrecruiters.com/NCS3/6000000001373525-it-support", "NCS3"),
    ("jobs.smartrecruiters.com/InterIKEAGroup", "InterIKEAGroup"),
])
def test_company_id_accepts_an_id_or_a_careers_link(entry, company):
    assert smartrecruiters._company_id(entry) == company


def test_location_text_marks_remote_and_hybrid_work():
    loc = {"city": "Älmhult", "country": "se", "fullLocation": "Älmhult, , Sweden"}
    assert smartrecruiters._location_text(loc) == "Älmhult, Sweden"
    assert smartrecruiters._location_text({**loc, "remote": True}) == "Remote, Älmhult, Sweden"
    assert smartrecruiters._location_text({"city": "Aarhus", "country": "dk"}) == "Aarhus, DK"
    assert smartrecruiters._location_text({"remote": True}) == "Remote"
    assert smartrecruiters._location_text(None) == ""


def test_description_joins_the_sections_in_order_and_strips_markup():
    sections = {
        "companyDescription": {"title": "Company Description", "text": "<p>Hej&#xa0;you</p>"},
        "jobDescription": {"title": "Job Description", "text": "<p>Do work</p><ul><li>one</li><li>two</li></ul>"},
        "qualifications": {"title": "Qualifications", "text": "<p>Know SQL</p>"},
        "additionalInformation": {"title": "Additional", "text": ""},
    }
    text = smartrecruiters._description(sections)
    assert text.index("Hej you") < text.index("Do work") < text.index("Know SQL")
    assert "one\ntwo" in text and "<" not in text
    assert smartrecruiters._description(None) == ""

# --- feed detection (issue #282) ---

def _d(det):
    return None if det is None else (det.platform, det.entry)


def test_detect_url_reads_a_careers_link():
    assert _d(smartrecruiters.detect_url("https://jobs.smartrecruiters.com/NCS3/6000000001373525-it-support")) == ("smartrecruiters", "ncs3")
    assert _d(smartrecruiters.detect_url("https://careers.smartrecruiters.com/InterIKEAGroup")) == ("smartrecruiters", "interikeagroup")
    assert smartrecruiters.detect_url("https://jobs.smartrecruiters.com/") is None


def test_detect_url_reads_the_company_an_employers_own_careers_site_links_to():
    """An employer's own careers site names its SmartRecruiters company in its staff sign-in and talent-community
    links (H&M's career.hm.com, issue #566)."""
    assert _d(smartrecruiters.detect_url("https://www.smartrecruiters.com/web-sso/saml/HMGroup/login")) == ("smartrecruiters", "hmgroup")
    assert _d(smartrecruiters.detect_url(
        "https://join.smartrecruiters.com/HMGroup/b00b30ef-7898-420d-acec-fc14a51a99c6-career-site_ec-newsletter")) == ("smartrecruiters", "hmgroup")
    assert smartrecruiters.detect_url("https://www.smartrecruiters.com/web-sso/saml/") is None
    assert smartrecruiters.detect_url("https://www.smartrecruiters.com/resources/") is None


def test_a_short_link_names_no_company():
    det = smartrecruiters.detect_url("https://au.smrtr.io/k7kb")
    assert det.platform == "smartrecruiters" and det.entry is None


def test_the_string_form_of_an_aggregator_link_names_the_company():
    det = smartrecruiters.detect_url("https://engradar.com/jobs/smartrecruiters:InterIKEAGroup:744000154654869")
    assert _d(det) == ("smartrecruiters", "interikeagroup")
    assert smartrecruiters.detect_url("https://engradar.com/jobs/greenhouse:acme:1") is None


def test_a_name_probe_is_the_postings_api():
    (probe,) = smartrecruiters.name_probes("acme")
    assert probe.url == "https://api.smartrecruiters.com/v1/companies/acme/postings"
    assert probe.key == "content" and probe.params == {"limit": 100}
    assert smartrecruiters.feed_url("acme") is None
