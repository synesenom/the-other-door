"""Unit tests for SuccessFactors pure helpers (unit layer).

Covers _extract_platform_id, _company_from_host,
_parse_pubdate, _parse_feed, and zero-result warning behaviour.
Pure and offline.
"""

import pytest

from door.scrapers.feeds import successfactors


# --------------------------------------------------------------------------- #
# _extract_platform_id
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "link,expected",
    [
        ("https://careers.novonordisk.com/job/Copenhagen-Senior-Data-Scientist/123456/", "123456"),
        ("https://careers.novonordisk.com/job/Copenhagen-Senior-Data-Scientist/123456?locale=en_US", "123456"),
        ("https://careers.novonordisk.com/job/no-id-here/", ""),
        (None, ""),
    ],
)
def test_extract_platform_id(link, expected):
    assert successfactors._extract_platform_id(link) == expected


# --------------------------------------------------------------------------- #
# _company_from_host / _company_from_channel_title / _channel_title
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "host,expected",
    [
        ("careers.novonordisk.com", "Novonordisk"),
        ("careers.ey.com", "Ey"),
        ("jobs.cph.dk", "Cph"),
        ("jobs.leo-pharma.com", "Leo Pharma"),
        ("jobs.coop.dk", "Coop"),
        ("careers.example.co.uk", "Example"),
        ("karriere.firma.dk", "Firma"),
        ("novonordisk.com", "Novonordisk"),
        ("", ""),
    ],
)
def test_company_from_host(host, expected):
    assert successfactors._company_from_host(host) == expected


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Novo Nordisk", "Novo Nordisk"),
        ("Available jobs at LEO Pharma", "LEO Pharma"),
        ("Careers at EY: search jobs", "EY"),
        ("Jobs at Tryg", "Tryg"),
        ("Tryg Careers | SAP SuccessFactors", "Tryg"),
        ("Novo Nordisk Careers", "Novo Nordisk"),
        ("Apply online for jobs at Ambu", "Ambu"),
        ("", ""),
        ("Careers", ""),
        ("Jobs", ""),
        ("Search jobs", ""),
        ("Careers | Tryg.com", "Tryg"),
        ("Tryg.dk | Karriere", "Tryg"),
        ("Jobs - Capgemini", "Capgemini"),
        ("Ledige stillinger: LEO Pharma", "LEO Pharma"),
        ("LEO Pharma \u2013 Ledige stillinger", "LEO Pharma"),
        ("Karriere | Ledige stillinger", ""),
        ("EY", "EY"),
        ("Novo Nordisk - Denmark", "Novo Nordisk - Denmark"),
        ("careers@lundbeck", "Lundbeck"),
        ("jobs@Ambu", "Ambu"),
    ],
)
def test_company_from_channel_title(title, expected):
    assert successfactors._company_from_channel_title(title) == expected


def test_channel_title_reads_the_channel_not_an_item():
    xml = "<rss><channel><title> Acme </title><item><title>Dev</title></item></channel></rss>"
    assert successfactors._channel_title(xml) == "Acme"
    assert successfactors._channel_title("<rss><channel><title/></channel></rss>") == ""
    assert successfactors._channel_title("not xml") == ""


def test_company_from_host_skips_every_countrys_generic_labels():
    assert successfactors._company_from_host("karrier.acme.hu") == "Acme"
    assert successfactors._company_from_host("acme.karrier.hu") == "Acme"
    assert successfactors._company_from_host("jobs.leo-pharma.com") == "Leo Pharma"
    assert successfactors._company_from_host("careers.acme.co.uk") == "Acme"


def test_company_name_prefers_channel_title_then_host():
    assert successfactors._company_name("Available jobs at LEO Pharma", "jobs.leo-pharma.com") == "LEO Pharma"
    assert successfactors._company_name("", "jobs.cph.dk") == "Cph"
    assert successfactors._company_name("Careers", "jobs.leo-pharma.com") == "Leo Pharma"


def test_job_id_carries_the_tenant_host():
    """The id is <site>.<platform_id>, the platform id folding in the host (ids repeat across tenants)."""
    from door.core.models import make_job_id
    a = successfactors._to_posting({"title": "Dev", "link": "https://jobs.cph.dk/job/x/1/"}, "Cph", "jobs.cph.dk-1",
                                   __import__("datetime").datetime(2026, 1, 1))
    assert a["id"] == make_job_id("successfactors", "jobs.cph.dk-1") == "successfactors.jobs-cph-dk-1"


# --------------------------------------------------------------------------- #
# _parse_pubdate
# --------------------------------------------------------------------------- #

def test_parse_pubdate_valid_rfc822():
    dt = successfactors._parse_pubdate("Mon, 27 Jul 2026 08:00:00 GMT")
    assert dt is not None and dt.year == 2026 and dt.month == 7


@pytest.mark.parametrize("bad", [None, "not-a-date"])
def test_parse_pubdate_invalid_returns_none(bad):
    assert successfactors._parse_pubdate(bad) is None


# --------------------------------------------------------------------------- #
# _parse_feed
# --------------------------------------------------------------------------- #

_SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>Novo Nordisk Careers</title>
<item>
<title>Senior Data Scientist</title>
<link>https://careers.novonordisk.com/job/Copenhagen-Senior-Data-Scientist/123456/</link>
<description><![CDATA[<p>Join our <b>team</b>.</p>]]></description>
<pubDate>Mon, 27 Jul 2026 08:00:00 GMT</pubDate>
</item>
<item>
<title>Principal ML Engineer</title>
<link>https://careers.novonordisk.com/job/Copenhagen-Principal-ML-Engineer/123457/</link>
<description><![CDATA[<p>No pub date here.</p>]]></description>
</item>
</channel>
</rss>
"""

_MALFORMED_FEED = "<rss><channel><item><title>Broken</item></channel>"

_EMPTY_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>Novo Nordisk Careers</title>
</channel>
</rss>
"""


def test_parse_feed_extracts_items():
    items = successfactors._parse_feed(_SAMPLE_FEED)
    assert len(items) == 2

    first = items[0]
    assert first["title"] == "Senior Data Scientist"
    assert first["link"] == "https://careers.novonordisk.com/job/Copenhagen-Senior-Data-Scientist/123456/"
    assert "<b>" in first["description"] or "team" in first["description"]
    assert first["pub_date"] == "Mon, 27 Jul 2026 08:00:00 GMT"

    second = items[1]
    assert second["title"] == "Principal ML Engineer"
    assert second["pub_date"] is None


def test_parse_feed_malformed_returns_empty():
    assert successfactors._parse_feed(_MALFORMED_FEED) == []


# --------------------------------------------------------------------------- #
# Zero-result warning / config edge cases
# --------------------------------------------------------------------------- #

def test_scrape_missing_key_returns_empty():
    result = successfactors.scrape({})
    assert result == []


# --------------------------------------------------------------------------- #
# _split_title_location / _location_from_suffix
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "raw,title,location",
    [
        ("Head of E-commerce (Ballerup, DK)", "Head of E-commerce", "Ballerup, DK"),
        ("E-commerce Lead (Bangkok, Bangkok, TH)", "E-commerce Lead", "Bangkok, TH"),
        ("RUN Service Delivery Manager (Pune, IN)", "RUN Service Delivery Manager", "Pune, IN"),
        (
            "AI & MarTech Lead (FGR Islevdalvej 151 Roedovre (, FGR Islevdalvej 151 Roedovre (Roedovre_FGR), DK, FGR Islevd)",
            "AI & MarTech Lead",
            "DK",
        ),
        ("Engineer (m/f/d) (Ballerup, DK)", "Engineer (m/f/d)", "Ballerup, DK"),
        ("Engineer (m/f/d)", "Engineer (m/f/d)", ""),
        ("Technicien (Vernouillet - 28, Centre-Val de Loire, France, 28500)",
         "Technicien (Vernouillet - 28, Centre-Val de Loire, France, 28500)", ""),
        ("(Ballerup, DK)", "(Ballerup, DK)", ""),
        ("Plain title", "Plain title", ""),
        ("", "", ""),
    ],
)
def test_split_title_location(raw, title, location):
    assert successfactors._split_title_location(raw) == (title, location)


def test_parse_feed_reads_the_google_location():
    xml = (
        '<rss xmlns:g="http://base.google.com/ns/1.0"><channel><item><title>Dev (Ballerup, DK)</title>'
        "<link>https://x/job/a/1/</link><g:location>Ballerup, DK</g:location></item></channel></rss>"
    )
    assert successfactors._parse_feed(xml)[0]["location"] == "Ballerup, DK"


def test_to_posting_splits_location_off_the_title():
    from datetime import datetime
    item = {"title": "Head of E-commerce (Ballerup, DK)", "link": "https://x/job/a/1/", "location": ""}
    p = successfactors._to_posting(item, "Tryg", "1", datetime(2026, 1, 1))
    assert (p["title"], p["location"]) == ("Head of E-commerce", "Ballerup, DK")
    item["location"] = "Ballerup, Denmark"
    assert successfactors._to_posting(item, "Tryg", "1", datetime(2026, 1, 1))["location"] == "Ballerup, Denmark"

# --- feed detection (issue #282) ---

def _d(det):
    return None if det is None else (det.platform, det.entry)


def test_detect_url_and_cname():
    assert _d(successfactors.detect_url("https://novonordisk.jobs2web.com/job/x/123/")) == (
        "successfactors", "novonordisk.jobs2web.com")
    # an older career2.successfactors.eu link names its company but has no job list of its own
    assert successfactors.detect_url("https://career2.successfactors.eu/career?company=pfapensionP&career_job_req_id=1") is None
    assert _d(successfactors.detect_cname("careers.veo.co", "novonordisk.jobs2web.com", "w")) == (
        "successfactors", "careers.veo.co")
    assert successfactors.detect_cname("careers.veo.co", "acme.github.io", "w") is None
    assert successfactors.feed_url("x.jobs2web.com") is None


def test_detect_html_recognises_an_rmk_career_site():
    rmk = '<script src="https://rmkcdn.successfactors.com/abc/js/x.js"></script>'
    assert _d(successfactors.detect_html(rmk, "https://careers.novonordisk.com/x")) == (
        "successfactors", "careers.novonordisk.com")
    assert successfactors.detect_html("<a>jobs2web</a>", "https://careers.acme.dk/").platform == "successfactors"
    assert successfactors.detect_html("<p>x</p>", "https://careers.acme.dk/") is None
