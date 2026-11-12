"""Fixture tests for the full TeamTailor scrape() path (fixture layer).

HTTP is mocked with ``responses`` from a hand-trimmed real payload shape.
No network access during these tests.
"""

import json
from pathlib import Path

import pytest
import responses as responses_lib

from door.core.models import JobPosting
from door.scrapers import drain_errors
from door.scrapers.feeds import teamtailor

_FIX = Path(__file__).parent / "fixtures" / "teamtailor"

_JOBS_URL = "https://acme.teamtailor.com/jobs.json"
_ROBOTS_URL = "https://acme.teamtailor.com/robots.txt"


def _fx(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


@responses_lib.activate
def test_scrape_maps_fields_and_strips_html():
    """Scrape with two real jobs: verify field mapping, HTML stripping, model validity."""
    responses_lib.add(responses_lib.GET, _ROBOTS_URL, body="User-agent: *\n",
                       content_type="text/plain")
    responses_lib.add(responses_lib.GET, _JOBS_URL, body=_fx("jobs_page.json"),
                       content_type="application/feed+json")

    postings = teamtailor.scrape({"teamtailor_companies": ["acme"]})

    assert len(postings) == 2

    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "teamtailor"
        assert p["company"] == "Storytel"  # from feed-level "title"
        assert p["title"] and p["url"]
        assert "<" not in p["description"]
        assert "&lt;" not in p["description"]
        assert p["apply_type"] == "external"
        assert p["apply_url"] == p["url"]

    by_id = {p["platform_id"]: p for p in postings}

    multi = by_id["storytel.teamtailor.com-8124466"]
    assert multi["title"] == "Software Engineer, AI Agents"
    assert multi["location"] == "Stockholm, SE; Umeå, SE"
    assert multi["posted_at"] is not None

    single = by_id["storytel.teamtailor.com-8124512"]
    assert single["title"] == "Customer Support Specialist"
    assert single["location"] == "Copenhagen, DK"


@responses_lib.activate
def test_scrape_empty_board_returns_no_postings(capsys, progress_events):
    """A board with no jobs prints a message and returns an empty list."""
    responses_lib.add(responses_lib.GET, _ROBOTS_URL, body="User-agent: *\n",
                       content_type="text/plain")
    responses_lib.add(responses_lib.GET, _JOBS_URL, body=_fx("jobs_empty.json"),
                       content_type="application/feed+json")

    postings = teamtailor.scrape({"teamtailor_companies": ["acme"]})

    assert postings == []
    assert any("0 results" in e.message for e in progress_events)
    assert capsys.readouterr().out == ""


@responses_lib.activate
def test_scrape_http_error_returns_empty(progress_events):
    """An HTTP 500 from the jobs endpoint is swallowed; scrape returns []."""
    responses_lib.add(responses_lib.GET, _ROBOTS_URL, body="User-agent: *\n",
                       content_type="text/plain")
    responses_lib.add(responses_lib.GET, _JOBS_URL, status=500)

    drain_errors()
    postings = teamtailor.scrape({"teamtailor_companies": ["acme"]})
    assert postings == []

    assert any("error fetching 'acme'" in e.message for e in progress_events)
    errors = drain_errors()
    assert "teamtailor" in errors


@responses_lib.activate
def test_scrape_deduplicates_jobs():
    """The same numeric id on two boards is two postings: ids repeat across tenants (#313)."""
    jobs_url2 = "https://contoso.teamtailor.com/jobs.json"
    robots_url2 = "https://contoso.teamtailor.com/robots.txt"

    responses_lib.add(responses_lib.GET, _ROBOTS_URL, body="User-agent: *\n",
                       content_type="text/plain")
    responses_lib.add(responses_lib.GET, _JOBS_URL, body=_fx("jobs_page.json"),
                       content_type="application/feed+json")

    responses_lib.add(responses_lib.GET, robots_url2, body="User-agent: *\n",
                       content_type="text/plain")
    contoso_jobs = json.dumps({
        "title": "Contoso",
        "items": [
            {
                "id": "33333333-3333-3333-3333-333333333333",
                "title": "Duplicate Job",
                "url": "https://contoso.teamtailor.com/jobs/8124466-duplicate",
                "date_published": "2026-05-01T12:00:00Z",
                "content_html": "",
                "_jobposting": {
                    "identifier": {"value": 8124466},
                    "jobLocation": [],
                },
            }
        ],
    })
    responses_lib.add(responses_lib.GET, jobs_url2, body=contoso_jobs,
                       content_type="application/feed+json")

    postings = teamtailor.scrape({"teamtailor_companies": ["acme", "contoso"]})

    ids = [p["platform_id"] for p in postings]
    assert ids.count("storytel.teamtailor.com-8124466") == 1 and ids.count("contoso.teamtailor.com-8124466") == 1
    assert len({p["id"] for p in postings}) == len(postings) == 3


@pytest.mark.usefixtures("obey_robots")
@pytest.mark.real_robots
@responses_lib.activate
def test_scrape_respects_robots_txt_disallow(capsys, progress_events):
    """robots.txt disallow on /jobs.json prevents the fetch (unlike sibling ATS scrapers)."""
    responses_lib.add(
        responses_lib.GET, _ROBOTS_URL,
        body="User-agent: *\nDisallow: /jobs.json\n",
        content_type="text/plain",
    )

    postings = teamtailor.scrape({"teamtailor_companies": ["acme"]})

    assert postings == []
    # The jobs.json endpoint itself must never have been called.
    called_urls = [call.request.url for call in responses_lib.calls]
    assert not any("jobs.json" in url for url in called_urls)
    assert any("acme" in e.message for e in progress_events)
    assert capsys.readouterr().out == ""


# --------------------------------------------------------------------------- #
# probe (issue #178)
# --------------------------------------------------------------------------- #

_PROBE_CFG = {"teamtailor_companies": ["acme", "other"]}


@responses_lib.activate
def test_probe_ok_uses_the_first_board_only():
    import json  # noqa: F401

    body = _fx("jobs_page.json")
    responses_lib.add(responses_lib.GET, _ROBOTS_URL, body='')
    responses_lib.add(responses_lib.GET, _JOBS_URL, body=body)
    drain_errors()
    result = teamtailor.probe(_PROBE_CFG)
    assert result["structure_ok"] is True and result["ext"] == "json" and result["raw"] == body
    assert result["postings"]
    for p in result["postings"]:
        JobPosting.model_validate(p)
    assert [c.request.url.split("?")[0] for c in responses_lib.calls if "robots" not in c.request.url] == [_JOBS_URL]
    assert drain_errors() == {}


@responses_lib.activate
def test_probe_drift_when_structure_is_broken():
    import json  # noqa: F401

    responses_lib.add(responses_lib.GET, _ROBOTS_URL, body='')
    responses_lib.add(responses_lib.GET, _JOBS_URL, body=json.dumps({"title": "Acme"}))
    result = teamtailor.probe(_PROBE_CFG)
    assert result["structure_ok"] is False and result["reason"]
    assert not result.get("wall") and not result.get("unreachable")




# --------------------------------------------------------------------------- #
# Custom hosts, pages, the RSS fallback (issue #227)
# --------------------------------------------------------------------------- #

def _feed(ids):
    return json.dumps({"title": "Acme", "items": [
        {"id": f"uuid-{i}", "title": f"Job {i}", "url": f"https://acme.teamtailor.com/jobs/{i}-job",
         "content_html": "<p>Ad</p>", "_jobposting": {"identifier": {"value": i}}} for i in ids]})


@responses_lib.activate
def test_scrape_reads_further_pages_until_one_adds_nothing():
    from responses import matchers

    responses_lib.add(responses_lib.GET, _JOBS_URL, body=_feed([1, 2]), match=[matchers.query_string_matcher("")])
    responses_lib.add(responses_lib.GET, _JOBS_URL, body=_feed([3]), match=[matchers.query_param_matcher({"page": "2"})])
    responses_lib.add(responses_lib.GET, _JOBS_URL, body=_feed([]), match=[matchers.query_param_matcher({"page": "3"})])

    postings = teamtailor.scrape({"teamtailor_companies": ["acme"]})

    assert [p["platform_id"] for p in postings] == [f"acme.teamtailor.com-{n}" for n in (1, 2, 3)]


@responses_lib.activate
def test_a_page_repeating_the_first_ends_the_paging():
    responses_lib.add(responses_lib.GET, _JOBS_URL, body=_feed([1, 2]))

    postings = teamtailor.scrape({"teamtailor_companies": ["acme"]})

    assert [p["platform_id"] for p in postings] == [f"acme.teamtailor.com-{n}" for n in (1, 2)]
    assert len([c for c in responses_lib.calls if "jobs.json" in c.request.url]) == 2


@responses_lib.activate
def test_a_custom_career_host_is_read_like_a_slug():
    responses_lib.add(responses_lib.GET, "https://careers.acme.dk/jobs.json", body=_feed([7]))

    postings = teamtailor.scrape({"teamtailor_companies": ["careers.acme.dk"]})

    assert [p["platform_id"] for p in postings] == ["acme.teamtailor.com-7"]


@responses_lib.activate
def test_the_rss_feed_is_the_fallback_when_jobs_json_fails():
    responses_lib.add(responses_lib.GET, "https://templafy.teamtailor.com/jobs.json", status=404)
    responses_lib.add(responses_lib.GET, "https://templafy.teamtailor.com/jobs.rss",
                      body=_fx("jobs_templafy.rss"), content_type="application/rss+xml")

    drain_errors()
    postings = teamtailor.scrape({"teamtailor_companies": ["templafy"]})

    assert [p["platform_id"] for p in postings] == ["templafy.teamtailor.com-8483649", postings[1]["platform_id"]]
    assert postings[0]["company"] == "Templafy" and postings[0]["description"]
    for p in postings:
        JobPosting.model_validate(p)
    assert drain_errors() == {}


@responses_lib.activate
def test_the_followed_name_wins_in_the_json_feed():
    responses_lib.add(responses_lib.GET, _ROBOTS_URL, body="User-agent: *\n", content_type="text/plain")
    responses_lib.add(responses_lib.GET, _JOBS_URL, body=_fx("jobs_page.json"), content_type="application/feed+json")

    postings = teamtailor.scrape({"teamtailor_companies": ["Acme"],
                                  "_names": {"teamtailor_companies": {"acme": "Acme A/S"}}})

    assert postings and {p["company"] for p in postings} == {"Acme A/S"}
    assert all(p["id"].startswith("teamtailor.") for p in postings)


@responses_lib.activate
def test_the_followed_name_wins_in_the_rss_fallback():
    responses_lib.add(responses_lib.GET, "https://templafy.teamtailor.com/jobs.json", status=404)
    responses_lib.add(responses_lib.GET, "https://templafy.teamtailor.com/jobs.rss",
                      body=_fx("jobs_templafy.rss"), content_type="application/rss+xml")

    postings = teamtailor.scrape({"teamtailor_companies": ["templafy"],
                                  "_names": {"teamtailor_companies": {"templafy": "Templafy ApS"}}})

    assert postings and {p["company"] for p in postings} == {"Templafy ApS"}


@responses_lib.activate
def test_the_json_feed_drops_postings_in_another_country_and_counts_them():
    from door.scrapers import drain_non_local
    data = json.loads(_fx("jobs_page.json"))
    place = data["items"][1]["_jobposting"]["jobLocation"][0]["address"]
    place.update(addressLocality="Budapest", addressCountry="HU")
    responses_lib.add(responses_lib.GET, _ROBOTS_URL, body="User-agent: *\n", content_type="text/plain")
    responses_lib.add(responses_lib.GET, _JOBS_URL, body=json.dumps(data), content_type="application/feed+json")
    drain_non_local("teamtailor")

    postings = teamtailor.scrape({"teamtailor_companies": ["acme"], "location": "Budapest, Hungary"})

    assert [p["location"] for p in postings] == ["Budapest, HU"]
    assert drain_non_local("teamtailor") == 1


@responses_lib.activate
def test_the_rss_fallback_drops_postings_in_another_country_and_counts_them():
    from door.scrapers import drain_non_local
    rss = _fx("jobs_templafy.rss").replace("<tt:name>Copenhagen</tt:name>", "<tt:name>London</tt:name>", 1) \
        .replace("<tt:city>København</tt:city>", "<tt:city>London</tt:city>", 1) \
        .replace("<tt:country>Denmark</tt:country>", "<tt:country>United Kingdom</tt:country>", 1)
    responses_lib.add(responses_lib.GET, "https://templafy.teamtailor.com/jobs.json", status=404)
    responses_lib.add(responses_lib.GET, "https://templafy.teamtailor.com/jobs.rss", body=rss,
                      content_type="application/rss+xml")
    drain_non_local("teamtailor")

    postings = teamtailor.scrape({"teamtailor_companies": ["templafy"], "location": "Budapest, Hungary"})

    assert "templafy.teamtailor.com-8483649" not in [p["platform_id"] for p in postings]
    assert drain_non_local("teamtailor") >= 1
