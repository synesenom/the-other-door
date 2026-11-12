"""Unit tests for the Signatur job portal's pure helpers."""

import pytest

from door.scrapers.feeds import signatur


@pytest.mark.parametrize("entry, client", [
    ("1449", "1449"),
    (" 2296 ", "2296"),
    ("https://portal.signatur.dk/ExtJobs/DefaultHosting/JobApplication.aspx?ClientId=1449&ERId=131713", "1449"),
    ("portal.signatur.dk/ExtJobs/DefaultHosting/JobList.aspx?clientid=2296", "2296"),
])
def test_client_id_accepts_an_id_or_a_portal_link(entry, client):
    assert signatur._client_id(entry) == client


def test_parse_list_reads_titles_ids_and_the_employer():
    html = """<html><head><title>
        Acme Kommune - Ledige stillinger</title></head><body>
        <a href="/ExtJobs/DefaultHosting/JobDetails.aspx?ClientId=7&WebAdId=11"><div><span class="screenReaderHint">Kategori: X. Stilling: </span>Pædagog søges<div class="visible-xs">Frist</div></div></a>
        <a href="/ExtJobs/DefaultHosting/JobDetails.aspx?ClientId=7&WebAdId=11">dup</a>
        <a href="/other">x</a></body></html>"""
    company, jobs = signatur._parse_list(html)
    assert company == "Acme Kommune"
    assert jobs == [{"id": "11", "title": "Pædagog søges"}]


def test_parse_list_without_a_title_has_no_company():
    assert signatur._parse_list("<html></html>") == (None, [])


def test_parse_detail_reads_title_location_and_body():
    html = """<html><body><h1 id="ctl00_mainContent_contentHeadlineH1">Jurist</h1>
        <input type="hidden" id="ctl00_mainContent_googleMapAddressHf" value="Stengade+59,+3000,+Helsingør,+Danmark" />
        <div id="ctl00_mainContent_contentBodyOuterDiv"><b>Intro</b><br/>Line&nbsp;two<ul><li>a</li><li>b</li></ul></div></body></html>"""
    detail = signatur._parse_detail(html)
    assert detail == {"title": "Jurist", "location": "Stengade 59, 3000, Helsingør, Danmark",
                      "description": "Intro\nLine two\na\nb"}


def test_parse_detail_of_an_unknown_page_is_none():
    assert signatur._parse_detail("<html><body>Fejl</body></html>") is None

# --- feed detection (issue #282) ---

def _d(det):
    return None if det is None else (det.platform, det.entry)


@pytest.mark.parametrize("url, client", [
    ("https://portal.signatur.dk/ExtJobs/DefaultHosting/JobApplication.aspx?ClientId=1449&ERId=131713", "1449"),
    ("https://portal.signatur.dk/ExtJobs/DefaultHosting/JobApplication.aspx?ClientId=2296&ERId=132159", "2296"),
    ("https://portal.signatur.dk/ExtJobs/DefaultHosting/JobList.aspx?clientid=2296", "2296"),
])
def test_detect_url_reads_the_client(url, client):
    assert _d(signatur.detect_url(url)) == ("signatur", client)


def test_a_link_without_a_client_is_not_a_feed():
    assert signatur.detect_url("https://portal.signatur.dk/ExtJobs/DefaultHosting/Default.aspx") is None
    assert signatur.detect_url("https://portal.signatur.dk/x?ClientId=abc") is None
    assert signatur.feed_url("1449") is None
