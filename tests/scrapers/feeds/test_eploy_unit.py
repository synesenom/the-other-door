"""Unit tests for Eploy's pure helpers (issue #603): the platform's public RSS data feed and how a host is recognised."""

import pytest

from door.scrapers.feeds import eploy
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "eploy"


def _read(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("entry, host", [
    ("vitalityweb.eploy.net", "vitalityweb.eploy.net"),
    (" VitalityWeb.eploy.net/ ", "vitalityweb.eploy.net"),
    ("https://portal.careers.turing.ac.uk/vacancies/171/partner-scientist.html", "portal.careers.turing.ac.uk"),
    ("http://mgroupweb.eploy.net/vacancies/vacancy-search-results.aspx?x=1", "mgroupweb.eploy.net"),
])
def test_host_accepts_a_host_or_a_link(entry, host):
    assert eploy._host(entry) == host


def test_the_feed_is_the_platforms_own_data_feed():
    assert eploy.datafeed_url("vitalityweb.eploy.net") == "https://vitalityweb.eploy.net/feeds/datafeed.ashx"
    assert eploy.datafeed_url("https://Portal.careers.turing.ac.uk/vacancies/") == \
        "https://portal.careers.turing.ac.uk/feeds/datafeed.ashx"
    assert eploy.alive_url("vitalityweb.eploy.net") == eploy.datafeed_url("vitalityweb.eploy.net")
    assert eploy.feed_url("vitalityweb.eploy.net") is None   # RSS, not the JSON list `companies add` confirms by


@pytest.mark.parametrize("url, host", [
    ("https://vitalityweb.eploy.net/vacancies/21883/head-of-events-and-experiences.html", "vitalityweb.eploy.net"),
    ("https://mgroupweb.eploy.net/vacancies/vacancy-search-results.aspx", "mgroupweb.eploy.net"),
    ("http://cardiffuniversityweb.eploy.net/", "cardiffuniversityweb.eploy.net"),
])
def test_detect_url_names_the_host(url, host):
    det = eploy.detect_url(url)
    assert (det.platform, det.entry) == ("eploy", host)
    assert det.config_key == "eploy_hosts"


@pytest.mark.parametrize("url", [
    "https://www.eploy.net/", "https://eploy.net/", "https://a.b.eploy.net/", "https://x.example.com/vacancies/1/a.html",
    "https://www.eploy.co.uk/",
])
def test_detect_url_ignores_what_is_no_customer_host(url):
    assert eploy.detect_url(url) is None


def test_detect_html_recognises_a_custom_domain_by_its_footer_and_vacancy_pages():
    det = eploy.detect_html(_read("portal_home.html"), "https://portal.careers.turing.ac.uk/")
    assert (det.platform, det.entry) == ("eploy", "portal.careers.turing.ac.uk")
    assert "Eploy" in det.evidence


@pytest.mark.parametrize("html", [
    "<html><body>Hello</body></html>",
    "<footer>Powered by <a href='https://www.eploy.co.uk'>Eploy</a></footer>",   # a mention, no vacancy pages
    "<a href='/vacancies/vacancy-search-results.aspx'>Jobs</a>",                  # no footer signature
    "",
])
def test_detect_html_needs_both_signatures(html):
    assert eploy.detect_html(html, "https://example.org/") is None


def test_job_id_is_the_number_in_the_vacancy_path():
    assert eploy._job_id("https://vitalityweb.eploy.net/vacancies/21883/head-of-events.html") == "21883"
    assert eploy._job_id("https://x.example/vacancies/vacancy-search-results.aspx") == ""
    assert eploy._job_id("") == ""


def test_parse_feed_reads_the_employer_and_every_ad():
    employer, ads = eploy.parse_feed(_read("vitality_feed.xml"))
    assert employer == "Vitality"
    assert [a["id"] for a in ads] == ["21883", "21880", "21824"]
    first, second, third = ads
    assert first["title"] == "Head of Events and Experiences"
    assert first["url"] == "https://vitalityweb.eploy.net/vacancies/21883/head-of-events-and-experiences.html"
    assert first["location"] == "London"
    assert first["posted_at"].isoformat().startswith("2026-11-03T00:00:00")
    assert second["title"] == "Information Security Analyst"           # trailing blanks dropped
    assert second["location"] == "London, Bournemouth, Stockport"       # the extra places are the ad's places too
    assert third["location"] == "Hong Kong, Shanghai"


def test_parse_feed_description_is_plain_text_with_the_whole_ad():
    _employer, ads = eploy.parse_feed(_read("vitality_feed.xml"))
    text = ads[0]["description"]
    assert "<" not in text and "&amp;" not in text and "&nbsp;" not in text
    assert "Marketing & PR" in text and "Salary" in text and "Competitive" in text
    assert "A record of running a large events programme" in text      # a list item inside the nested role text
    assert "report to the Marketing Director" in text
    assert "pension scheme & a private health plan" in ads[1]["description"]


def test_parse_feed_rejects_what_is_no_feed():
    for text in ["<html><body>Maintenance</body></html>", "", "Not Found", "<rss><nothing/></rss>"]:
        with pytest.raises(ValueError):
            eploy.parse_feed(text)


def test_an_empty_feed_is_a_feed_without_ads():
    employer, ads = eploy.parse_feed(
        '<?xml version="1.0"?><rss version="2.0"><channel><title>Acme - Vacancies</title></channel></rss>')
    assert (employer, ads) == ("Acme", [])


def test_channel_name_drops_the_vacancies_suffix():
    assert eploy._channel_name("The Alan Turing Institute - Vacancies") == "The Alan Turing Institute"
    assert eploy._channel_name("M Group Ltd - Vacancies") == "M Group Ltd"
    assert eploy._channel_name("Plain") == "Plain"


def test_a_pubdate_that_does_not_parse_is_no_date():
    xml = _read("vitality_feed.xml").replace("Tue, 03 Nov 2026 00:00:00 GMT</pubDate><guid>", "soon</pubDate><guid>", 1)
    _employer, ads = eploy.parse_feed(xml)
    assert ads[0]["posted_at"] is None
