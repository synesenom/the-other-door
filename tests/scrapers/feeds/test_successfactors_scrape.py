"""Fixture tests for the full SuccessFactors scrape() path (fixture layer).

HTTP is mocked with ``responses`` from a hand-constructed, real-shaped
``sitemal.xml`` RSS payload. No network access during these tests.

This is the first scraper to use ``check_robots=True`` end to end, so the
suite also exercises both the robots-allow and robots-disallow branches
against a mocked ``robots.txt``.
"""

from pathlib import Path

import pytest
import responses as responses_lib

from door.core.models import JobPosting
from door.scrapers import drain_errors
from door.scrapers.feeds import successfactors

_FIX = Path(__file__).parent / "fixtures" / "successfactors"

_HOST = "careers.novonordisk.com"
_FEED_URL = f"https://{_HOST}/sitemal.xml"
_ROBOTS_URL = f"https://{_HOST}/robots.txt"


def _fx(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


def _allow_robots():
    responses_lib.add(
        responses_lib.GET, _ROBOTS_URL,
        body="User-agent: *\nDisallow: /services/\n",
        content_type="text/plain",
    )


@responses_lib.activate
def test_scrape_maps_fields_and_strips_html():
    """Scrape with three real-shaped jobs: verify field mapping, HTML stripping, model validity."""
    _allow_robots()
    responses_lib.add(responses_lib.GET, _FEED_URL, body=_fx("feed_sample.xml"),
                       content_type="application/rss+xml")

    postings = successfactors.scrape({"successfactors_companies": [_HOST]})

    assert len(postings) == 3

    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "successfactors"
        assert p["company"] == "Novo Nordisk"
        assert p["title"] and p["url"]
        assert "<" not in p["description"]
        assert "&lt;" not in p["description"]
        assert p["apply_type"] == "external"
        assert p["apply_url"] == p["url"]

    by_id = {p["platform_id"]: p for p in postings}

    sds = by_id["careers.novonordisk.com-123456"]
    assert sds["title"] == "Senior Data Scientist"
    assert sds["url"] == "https://careers.novonordisk.com/job/Copenhagen-Senior-Data-Scientist/123456/"
    assert sds["posted_at"] is not None
    assert sds["id"] == "successfactors." + sds["platform_id"].replace(".", "-")

    hds = by_id["careers.novonordisk.com-123458"]
    assert hds["title"] == "Head of Data Science"
    assert hds["posted_at"] is None  # no pubDate on this item


@responses_lib.activate
def test_scrape_empty_feed_returns_no_postings(capsys, progress_events):
    """A host with no items prints a message and returns an empty list."""
    _allow_robots()
    responses_lib.add(responses_lib.GET, _FEED_URL, body=_fx("feed_empty.xml"),
                       content_type="application/rss+xml")

    postings = successfactors.scrape({"successfactors_companies": [_HOST]})

    assert postings == []
    assert any("0 results" in e.message for e in progress_events)
    assert capsys.readouterr().out == ""


@responses_lib.activate
def test_scrape_http_error_returns_empty(progress_events):
    """An HTTP 500 from the feed endpoint is swallowed; scrape returns []."""
    _allow_robots()
    responses_lib.add(responses_lib.GET, _FEED_URL, status=500)

    drain_errors()
    postings = successfactors.scrape({"successfactors_companies": [_HOST]})
    assert postings == []
    assert any("error fetching" in e.message for e in progress_events)

    errors = drain_errors()
    assert "successfactors" in errors


@pytest.mark.usefixtures("obey_robots")
@pytest.mark.real_robots
@responses_lib.activate
def test_scrape_robots_disallow_returns_empty():
    """robots.txt disallowing /sitemal.xml is swallowed; scrape returns []."""
    responses_lib.add(
        responses_lib.GET, _ROBOTS_URL,
        body="User-agent: *\nDisallow: /sitemal.xml\n",
        content_type="text/plain",
    )
    # The feed URL should never actually be fetched, but register it anyway
    # so a mistaken request doesn't hit the network / raise ConnectionError.
    responses_lib.add(responses_lib.GET, _FEED_URL, body=_fx("feed_sample.xml"),
                       content_type="application/rss+xml")

    postings = successfactors.scrape({"successfactors_companies": [_HOST]})
    assert postings == []


@responses_lib.activate
def test_scrape_deduplicates_jobs():
    """The same numeric id on two hosts is two postings (ids repeat across tenants, #313); one host never repeats one."""
    host2 = "careers.example.com"
    feed_url2 = f"https://{host2}/sitemal.xml"
    robots_url2 = f"https://{host2}/robots.txt"

    _allow_robots()
    responses_lib.add(responses_lib.GET, _FEED_URL, body=_fx("feed_sample.xml"),
                       content_type="application/rss+xml")

    responses_lib.add(
        responses_lib.GET, robots_url2,
        body="User-agent: *\nDisallow: /services/\n",
        content_type="text/plain",
    )
    dup_feed = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
<title>Duplicate Job</title>
<link>https://careers.example.com/job/Duplicate/123456/</link>
<description><![CDATA[<p>Dup</p>]]></description>
</item>
</channel></rss>
"""
    responses_lib.add(responses_lib.GET, feed_url2, body=dup_feed,
                       content_type="application/rss+xml")

    postings = successfactors.scrape({"successfactors_companies": [_HOST, host2]})

    ids = [p["platform_id"] for p in postings]
    assert ids.count("careers.novonordisk.com-123456") == 1 and ids.count("careers.example.com-123456") == 1
    assert len({p["id"] for p in postings}) == len(postings) == 4  # 3 from novonordisk, 1 from example.com


# --------------------------------------------------------------------------- #
# probe (issue #178)
# --------------------------------------------------------------------------- #

_PROBE_CFG = {"successfactors_companies": [_HOST, "other.example.com"]}


@responses_lib.activate
def test_probe_ok_uses_the_first_board_only():
    import json  # noqa: F401

    body = _fx("feed_sample.xml")
    responses_lib.add(responses_lib.GET, _ROBOTS_URL, body='')
    responses_lib.add(responses_lib.GET, _FEED_URL, body=body)
    drain_errors()
    result = successfactors.probe(_PROBE_CFG)
    assert result["structure_ok"] is True and result["ext"] == "xml" and result["raw"] == body
    assert result["postings"]
    for p in result["postings"]:
        JobPosting.model_validate(p)
    assert [c.request.url.split("?")[0] for c in responses_lib.calls if "robots" not in c.request.url] == [_FEED_URL]
    assert drain_errors() == {}


@responses_lib.activate
def test_probe_drift_when_structure_is_broken():
    import json  # noqa: F401

    responses_lib.add(responses_lib.GET, _ROBOTS_URL, body='')
    responses_lib.add(responses_lib.GET, _FEED_URL, body="<html><body>Sign in</body></html>")
    result = successfactors.probe(_PROBE_CFG)
    assert result["structure_ok"] is False and result["reason"]
    assert not result.get("wall") and not result.get("unreachable")




@responses_lib.activate
def test_no_request_ever_goes_to_a_services_path():
    """`/services/` is robots-disallowed on RMK hosts and must never be used (issue #227)."""
    _allow_robots()
    responses_lib.add(responses_lib.GET, _FEED_URL, body=_fx("feed_sample.xml"), content_type="application/rss+xml")

    successfactors.scrape({"successfactors_companies": [_HOST]})
    successfactors.probe({"successfactors_companies": [_HOST]})

    assert not any("/services/" in c.request.url for c in responses_lib.calls)


def _feed_for(host, fixture):
    responses_lib.add(responses_lib.GET, f"https://{host}/robots.txt",
                      body="User-agent: *\nDisallow: /services/\n", content_type="text/plain")
    responses_lib.add(responses_lib.GET, f"https://{host}/sitemal.xml", body=_fx(fixture),
                      content_type="application/rss+xml")


@responses_lib.activate
def test_scrape_names_employer_from_channel_title():
    """Real jobs.leo-pharma.com channel: 'Available jobs at LEO Pharma' -> 'LEO Pharma', not 'jobs'."""
    _feed_for("jobs.leo-pharma.com", "feed_channel_titled.xml")
    postings = successfactors.scrape({"successfactors_companies": ["jobs.leo-pharma.com"]})
    assert postings
    assert {p["company"] for p in postings} == {"LEO Pharma"}
    assert all(p["id"].startswith("successfactors.") for p in postings)


@responses_lib.activate
def test_scrape_falls_back_to_domain_when_channel_title_blank():
    """Real jobs.cph.dk channel has an empty <title>: the registrable domain label is used."""
    _feed_for("jobs.cph.dk", "feed_channel_blank.xml")
    postings = successfactors.scrape({"successfactors_companies": ["jobs.cph.dk"]})
    assert postings
    assert {p["company"] for p in postings} == {"Cph"}


@responses_lib.activate
def test_scrape_cleans_company_and_splits_location_from_title():
    """Tryg channel 'Careers | Tryg.com' -> 'Tryg'; '(City, CC)' title suffixes become the location."""
    _feed_for("careers.tryg.com", "feed_tryg_locations.xml")
    postings = successfactors.scrape({"successfactors_companies": ["careers.tryg.com"]})
    assert {p["company"] for p in postings} == {"Tryg"}
    got = {p["platform_id"]: (p["title"], p["location"]) for p in postings}
    assert got == {
        "careers.tryg.com-1001": ("Head of E-commerce", "Ballerup, DK"),
        "careers.tryg.com-1002": ("Agil projektledare (Epic Owner)", "Stockholm, SE"),
        "careers.tryg.com-1003": ("E-commerce Lead", "Bangkok, TH"),
        "careers.tryg.com-1004": ("AI & MarTech Lead", "DK"),
        "careers.tryg.com-1005": ("Engineer (m/f/d)", ""),
    }


@responses_lib.activate
def test_the_followed_name_wins():
    _allow_robots()
    responses_lib.add(responses_lib.GET, _FEED_URL, body=_fx("feed_sample.xml"), content_type="application/rss+xml")

    postings = successfactors.scrape({"successfactors_companies": [_HOST],
                                      "_names": {"successfactors_companies": {_HOST: "Novo Nordisk A/S"}}})

    assert len(postings) == 3 and {p["company"] for p in postings} == {"Novo Nordisk A/S"}
    assert all(p["id"].startswith("successfactors.") for p in postings)


@responses_lib.activate
def test_without_a_name_map_the_feed_name_is_the_fallback():
    _allow_robots()
    responses_lib.add(responses_lib.GET, _FEED_URL, body=_fx("feed_sample.xml"), content_type="application/rss+xml")

    assert {p["company"] for p in successfactors.scrape({"successfactors_companies": [_HOST]})} == {"Novo Nordisk"}


@responses_lib.activate
def test_scrape_drops_postings_in_another_country_and_counts_them():
    """Tryg's title suffixes: (Stockholm, SE) and (Bangkok, TH) are foreign to a Danish profile; DK, a bare
    country and no location at all stay."""
    from door.scrapers import drain_non_local
    _feed_for("careers.tryg.com", "feed_tryg_locations.xml")
    drain_non_local("successfactors")

    postings = successfactors.scrape({"successfactors_companies": ["careers.tryg.com"], "location": "Copenhagen, Denmark"})

    assert sorted(p["platform_id"] for p in postings) == [f"careers.tryg.com-{n}" for n in (1001, 1004, 1005)]
    assert drain_non_local("successfactors") == 2
