"""Unit tests for Jobindex pure helpers (C3, unit layer).

Covers _parse_stash, _teaser_text, and _area_for_profile in isolation.
Pure and offline — no network.
"""

import pytest

from door.scrapers import drain_errors
from door.scrapers.boards import jobindex
from paths import TESTS_DIR


# --------------------------------------------------------------------------- #
# _parse_stash
# --------------------------------------------------------------------------- #

def test_parse_stash_valid():
    html = 'before var Stash = {"a": {"b": 1}};\nafter'
    assert jobindex._parse_stash(html) == {"a": {"b": 1}}


def test_parse_stash_missing_returns_empty():
    assert jobindex._parse_stash("<html>no stash here</html>") == {}


# --------------------------------------------------------------------------- #
# _search_response
# --------------------------------------------------------------------------- #

def test_search_response_legacy_key():
    stash = {"jobsearch/result_app": {"storeData": {"searchResponse": {"results": [{"tid": "h1"}]}}}}
    assert jobindex._search_response(stash) == {"results": [{"tid": "h1"}]}


def test_search_response_list_key():
    """Jobindex renamed the app key to ``jobsearch/result_app/list`` (Oct 2026)."""
    stash = {
        "common": {},
        "jobsearch/result_app/list": {"storeData": {"searchResponse": {"results": [{"tid": "h2"}]}}},
    }
    assert jobindex._search_response(stash) == {"results": [{"tid": "h2"}]}


def test_search_response_missing_returns_none():
    assert jobindex._search_response({"common": {}, "login": {}}) is None
    assert jobindex._search_response({}) is None


# --------------------------------------------------------------------------- #
# _teaser_text
# --------------------------------------------------------------------------- #

def test_teaser_text_strips_toolbar_and_share():
    html = (
        '<div class="jix_robotjob">'
        '<div class="jix_toolbar">share buttons</div>'
        '<span class="jix_share">x</span>'
        'Real job text'
        "</div>"
    )
    assert jobindex._teaser_text(html) == "Real job text"


def test_teaser_text_empty_input():
    assert jobindex._teaser_text("") == ""


# --------------------------------------------------------------------------- #
# _area_for_profile
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "location,expected",
    [
        # Jobindex area path segments (/jobsoegning/<area>).
        ("Copenhagen", "storkoebenhavn"),
        ("København", "storkoebenhavn"),
        ("Aarhus", "region-midtjylland"),
        ("Odense", "region-syddanmark"),
        ("Aalborg", "region-nordjylland"),
        ("Esbjerg", ""),                           # unknown city: all of Denmark, not one region
        ("Remote, Denmark", ""),
        ("", ""),                                  # no location: all of Denmark
    ],
)
def test_area_for_profile(location, expected):
    assert jobindex._area_for_profile({"location": location}) == expected


# --------------------------------------------------------------------------- #
# Zero-result warning
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# Parse-error report in _parse_stash
# --------------------------------------------------------------------------- #

def test_parse_stash_malformed_json_reports_and_records_error(capsys, progress_events):
    """Malformed Stash JSON yields {}; it is reported (not printed) and recorded (#132, #202)."""
    drain_errors()
    assert jobindex._parse_stash("var Stash = {not valid json};\n") == {}
    assert any("parse error decoding Stash JSON" in e.message for e in progress_events)
    assert capsys.readouterr().out == ""
    errors = drain_errors()
    assert "jobindex" in errors
    assert "parse error" in errors["jobindex"][0].lower()


# --------------------------------------------------------------------------- #
# _parse_search / _to_posting (issue #178)
# --------------------------------------------------------------------------- #

from pathlib import Path  # noqa: E402

_FIXTURES = Path(__file__).parent / "fixtures" / "jobindex"


def _fx(name):
    return (_FIXTURES / name).read_text(encoding="utf-8")


def test_parse_search_without_results_block():
    assert jobindex._parse_search(_fx("search_drift.html")) == (None, [])
    assert jobindex._parse_search("var Stash = {not json};\n") == (None, [])


def test_to_posting_without_a_company_name():
    """Some ads carry `"company": null` and no `companytext` (#433): no name, not a crash."""
    from datetime import datetime, timezone

    raw = {"tid": "h1", "headline": "Lægevikar søges", "company": None, "companytext": None}
    posting = jobindex._to_posting(raw, "", datetime.now(timezone.utc))
    assert posting["title"] == "Lægevikar søges"
    assert posting["company"] == ""
    named = jobindex._to_posting({**raw, "company": {"name": "Klinik Østerbro"}}, "", datetime.now(timezone.utc))
    assert named["company"] == "Klinik Østerbro"


def test_parse_search_is_side_effect_free():
    drain_errors()
    jobindex._parse_search(_fx("search_drift.html"))
    jobindex._parse_search("var Stash = {not json};\n")
    assert drain_errors() == {}


# --------------------------------------------------------------------------- #
# _description_from_html
# --------------------------------------------------------------------------- #

def _detail(name: str) -> str:
    return (TESTS_DIR / "scrapers" / "boards" / "fixtures" / "jobindex" / name).read_text(encoding="utf-8")


def test_description_from_jobtext_body():
    # Jobindex-hosted ad, markup since Oct 2026: section.jobtext-jobad__body.
    text = jobindex._description_from_html(_detail("detail_h1705257_jobtext.html"))
    assert text.startswith("Hos Thales Denmark ApS")
    assert text.endswith("Jobbet søges via QuickApply på Jobindex.")
    assert len(text) > 4000


def test_description_from_branded_jobcontent_article():
    # Employer-branded ad hosted on Jobindex: article.jobcontent.
    text = jobindex._description_from_html(_detail("detail_h1705891_jobcontent.html"))
    assert "Help Shape the Next Stage of Procurement at Contura" in text
    assert len(text) > 4000


def test_description_from_branded_jobcontent_div():
    # Same branded layout as a <div> instead of an <article>.
    text = jobindex._description_from_html(_detail("detail_h1706510_div_jobcontent.html"))
    assert "Leder af AI Platform" in text
    assert len(text) > 5000


def test_description_from_legacy_read_more_container():
    text = jobindex._description_from_html(_detail("detail_h1673146.html"))
    assert len(text) > 1000


def test_description_from_external_page_json_ld():
    # /jobannonce/<tid>/ redirected to the employer's TeamTailor page; its
    # schema.org JobPosting JSON-LD carries the full ad.
    text = jobindex._description_from_html(_detail("detail_h1701970_external_jsonld.html"))
    assert "Most machine learning never makes it to production." in text
    assert "<" not in text  # HTML stripped
    assert len(text) > 4000


@pytest.mark.parametrize("ld", [
    '{"@type": "JobPosting", "description": "<p>Full <b>ad</b></p>"}',
    '[{"@type": "Organization"}, {"@type": "JobPosting", "description": "<p>Full <b>ad</b></p>"}]',
    '{"@graph": [{"@type": ["JobPosting"], "description": "<p>Full <b>ad</b></p>"}]}',
])
def test_description_from_json_ld_shapes(ld):
    html = f'<html><script type="application/ld+json">{ld}</script></html>'
    assert jobindex._description_from_html(html) == "Full\nad"


def test_description_from_html_without_any_known_source_is_empty():
    html = '<html><script type="application/ld+json">{not json</script><p>hi</p></html>'
    assert jobindex._description_from_html(html) == ""
    assert jobindex._description_from_html(_detail("detail_h1673246.html")) == ""


# --------------------------------------------------------------------------- #
# _main_text
# --------------------------------------------------------------------------- #

def test_main_text_reads_the_main_content_without_page_chrome():
    text = jobindex._main_text(_detail("employer_mindkey_main.html"))
    assert text.startswith("Team Lead, Resourcing & Impact")
    assert len(text) > 5000


def test_main_text_drops_cookie_banners():
    text = jobindex._main_text(_detail("employer_coop_main.html"))
    assert "accepter alle cookies" not in text.lower()
    assert len(text) < jobindex._MIN_MAIN_TEXT


# --------------------------------------------------------------------------- #
# Applicant-tracking systems that render the ad with JavaScript
# --------------------------------------------------------------------------- #



def test_hr_manager_ad_url_keeps_only_customer_and_project():
    # With DepartmentId/MediaId the page answers "Department is not set or unknown."
    url = "https://candidate.hr-manager.net/ApplicationInit.aspx?cid=1202&ProjectId=144266&DepartmentId=19128&MediaId=4630"
    assert jobindex._hr_manager_ad_url(url) == "https://candidate.hr-manager.net/ApplicationInit.aspx?cid=1202&ProjectId=144266"
    assert jobindex._hr_manager_ad_url("https://careers.example.com/job/1") is None


def test_hr_manager_text_is_the_advertisement_content():
    text = jobindex._hr_manager_text(_detail("hr_manager_ad_144266.html"))
    assert text.startswith("Machine Learning Engineer")
    assert "Hos nemlig er fundamentet på plads" in text
    assert "Din browser er forældet" not in text


def test_search_url_puts_the_area_in_the_path_and_pages_after_the_first_in_the_query():
    assert jobindex._search_url("data scientist", "") == "https://www.jobindex.dk/jobsoegning?q=%22data+scientist%22"
    assert jobindex._search_url("ml", "storkoebenhavn") == "https://www.jobindex.dk/jobsoegning/storkoebenhavn?q=ml"
    assert jobindex._search_url("ml", "", 2) == "https://www.jobindex.dk/jobsoegning?q=ml&page=2"
