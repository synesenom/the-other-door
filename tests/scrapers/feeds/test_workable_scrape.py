"""Fixture tests for the Workable job-search scrape() path (fixture layer).

HTTP is mocked with ``responses`` from saved real ``jobs.workable.com`` payloads. No network.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import responses as responses_lib

from door.core.models import JobPosting
from door.scrapers import drain_answered, drain_errors
from door.scrapers.feeds import workable

_FIX = Path(__file__).parent / "fixtures" / "workable"
_URL = workable._SEARCH_URL
_CFG = {"search_keywords": ["data scientist"], "location": "London"}


def _fx(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


def _query(call) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(call.request.url).query).items()}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _robots_allows_api():
    """jobs.workable.com/robots.txt disallows only /search and /profile paths, not the API."""
    with responses_lib.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses_lib.GET, "https://jobs.workable.com/robots.txt",
                 body="User-agent: *\nDisallow: /search\nDisallow: /profile*\n")
        yield rsps


def test_scrape_follows_page_tokens_and_maps_fields(_robots_allows_api):
    rsps = _robots_allows_api
    rsps.add(responses_lib.GET, _URL, body=_fx("search_page1.json"))
    rsps.add(responses_lib.GET, _URL, body=_fx("search_page2.json"))

    postings = workable.scrape(_CFG)

    assert len(postings) == 5
    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "workable"
        assert p["title"] and p["company"] and p["url"]
    assert {p["company"] for p in postings} >= {"Our Future Health", "LoopMe"}

    calls = [c for c in rsps.calls if "robots" not in c.request.url]
    assert len(calls) == 2
    first, second = _query(calls[0]), _query(calls[1])
    assert first == {"query": "data scientist", "location": "London"}
    token = json.loads(_fx("search_page1.json"))["nextPageToken"]
    assert second["pageToken"] == token


def test_scrape_stops_at_max_pages(_robots_allows_api):
    rsps = _robots_allows_api
    rsps.add(responses_lib.GET, _URL, body=_fx("search_page1.json"))

    postings = workable.scrape({**_CFG, "max_pages_per_keyword": 1})

    assert len(postings) == 3
    assert len([c for c in rsps.calls if "robots" not in c.request.url]) == 1


def test_scrape_dedups_across_keywords(_robots_allows_api):
    rsps = _robots_allows_api
    for _ in range(2):
        rsps.add(responses_lib.GET, _URL, body=_fx("search_page2.json"))

    postings = workable.scrape({"search_keywords": ["a", "b"], "location": "London"})

    assert len(postings) == 2


def test_scrape_drops_postings_older_than_since(_robots_allows_api):
    rsps = _robots_allows_api
    rsps.add(responses_lib.GET, _URL, body=_fx("search_page2.json"))

    since = datetime(2026, 7, 20, tzinfo=timezone.utc)
    postings = workable.scrape(_CFG, since=since)

    # page 2 holds one posting from 2026-07-22 and one from 2026-07-14
    assert [p["company"] for p in postings] == ["Arondite"]


def test_scrape_falls_back_to_role_targets_and_omits_empty_location(_robots_allows_api):
    rsps = _robots_allows_api
    rsps.add(responses_lib.GET, _URL, body=_fx("search_empty.json"))
    drain_answered("workable")

    assert workable.scrape({"role_targets": ["ML Lead"], "location": ""}) == []
    assert drain_answered("workable") is True
    calls = [c for c in rsps.calls if "robots" not in c.request.url]
    assert _query(calls[0]) == {"query": "ML Lead"}


def test_scrape_http_error_is_recorded_not_raised(_robots_allows_api, progress_events, capsys):
    for _ in range(5):
        _robots_allows_api.add(responses_lib.GET, _URL, status=500)
    drain_errors()

    assert workable.scrape(_CFG) == []

    assert any("search error" in e.message and "data scientist" in e.message for e in progress_events)
    assert capsys.readouterr().out == ""
    errors = drain_errors()
    assert any("data scientist" in m for m in errors["workable"])


def test_scrape_an_answer_without_a_job_list_is_not_a_quiet_day(_robots_allows_api):
    _robots_allows_api.add(responses_lib.GET, _URL, body=json.dumps({"unexpected": []}))
    drain_answered("workable")

    assert workable.scrape(_CFG) == []

    assert drain_answered("workable") is False


def test_scrape_without_keywords_makes_no_request():
    assert workable.scrape({"location": "London"}) == []


# --------------------------------------------------------------------------- #
# probe
# --------------------------------------------------------------------------- #

_PROBE_CFG = {"search_keywords": ["data scientist", "other"], "location": "London"}


def test_probe_ok_fetches_page_one_of_the_first_keyword_only(_robots_allows_api):
    rsps = _robots_allows_api
    body = _fx("search_page1.json")
    rsps.add(responses_lib.GET, _URL, body=body)
    drain_errors()

    result = workable.probe(_PROBE_CFG)

    assert result["structure_ok"] is True and result["ext"] == "json" and result["raw"] == body
    assert result["postings"]
    for p in result["postings"]:
        JobPosting.model_validate(p)
    calls = [c for c in rsps.calls if "robots" not in c.request.url]
    assert len(calls) == 1 and _query(calls[0])["query"] == "data scientist"
    assert drain_errors() == {}


def test_probe_drift_when_structure_is_broken(_robots_allows_api):
    _robots_allows_api.add(responses_lib.GET, _URL, body=json.dumps({"unexpected": []}))
    result = workable.probe(_PROBE_CFG)
    assert result["structure_ok"] is False and result["reason"]
    assert not result.get("wall") and not result.get("unreachable")




# --------------------------------------------------------------------------- #
# Per-company boards: workable_companies (issue #227)
# --------------------------------------------------------------------------- #

_WIDGET = "https://apply.workable.com/api/v1/widget/accounts/dreamdata"


def _widget():
    return (Path(__file__).parent / "fixtures" / "workable" / "widget_dreamdata.json").read_text(encoding="utf-8")


def test_a_listed_company_is_read_whole_with_descriptions(_robots_allows_api):
    from responses import matchers

    _robots_allows_api.add(responses_lib.GET, _WIDGET, body=_widget(), match=[matchers.query_param_matcher({"details": "true"})])

    postings = workable.scrape({"workable_companies": ["dreamdata"]})

    assert [p["title"] for p in postings] == ["RevOps Manager", postings[1]["title"]]
    first = postings[0]
    assert first["company"] == "Dreamdata"
    assert first["platform_id"] == "497E870DCF"
    assert first["url"] == "https://apply.workable.com/j/497E870DCF"
    assert first["location"] == "New York, United States"
    assert first["posted_at"].startswith("2026-06-22")
    assert first["description"].startswith("About Dreamdata")
    for p in postings:
        JobPosting.model_validate(p)


@pytest.mark.parametrize("entry", ["dreamdata", "https://apply.workable.com/dreamdata/", "apply.workable.com/dreamdata/j/497E870DCF"])
def test_account_accepts_a_slug_or_a_careers_url(entry):
    assert workable._account(entry) == "dreamdata"


def test_companies_and_keywords_are_both_read(_robots_allows_api):
    _robots_allows_api.add(responses_lib.GET, _WIDGET, body=_widget())
    _robots_allows_api.add(responses_lib.GET, workable._SEARCH_URL, json={"jobs": []})

    postings = workable.scrape({"workable_companies": ["dreamdata"], "search_keywords": ["data"]})

    assert len(postings) == 2
    assert {c.request.url.split("?")[0] for c in _robots_allows_api.calls if "robots" not in c.request.url} == {_WIDGET, workable._SEARCH_URL}


def _urls(rsps):
    return {c.request.url.split("?")[0] for c in rsps.calls if "robots" not in c.request.url}


def test_the_search_step_reads_only_the_keyword_search(_robots_allows_api):
    _robots_allows_api.add(responses_lib.GET, workable._SEARCH_URL, json={"jobs": []})
    workable.scrape({"workable_companies": ["dreamdata"], "search_keywords": ["data"], "_mode": "search"})
    assert _urls(_robots_allows_api) == {workable._SEARCH_URL}


def test_the_collect_step_reads_only_the_followed_accounts(_robots_allows_api):
    _robots_allows_api.add(responses_lib.GET, _WIDGET, body=_widget())
    postings = workable.scrape({"workable_companies": ["dreamdata"], "search_keywords": ["data"], "_mode": "collect"})
    assert len(postings) == 2 and _urls(_robots_allows_api) == {_WIDGET}


def test_a_company_that_fails_is_recorded_and_the_rest_continue(_robots_allows_api, progress_events):
    _robots_allows_api.add(responses_lib.GET, "https://apply.workable.com/api/v1/widget/accounts/gone", status=404)
    _robots_allows_api.add(responses_lib.GET, _WIDGET, body=_widget())

    drain_errors()
    postings = workable.scrape({"workable_companies": ["gone", "dreamdata"]})

    assert len(postings) == 2
    assert "gone" in drain_errors()["workable"][0]


def test_probe_reads_the_first_account_when_there_are_no_keywords(_robots_allows_api):
    _robots_allows_api.add(responses_lib.GET, _WIDGET, body=_widget())

    result = workable.probe({"workable_companies": ["dreamdata", "other"]})

    assert result["structure_ok"] is True and len(result["postings"]) == 2


def test_the_followed_name_wins_for_an_account(_robots_allows_api):
    _robots_allows_api.add(responses_lib.GET, _WIDGET, body=_widget())

    postings = workable.scrape({"workable_companies": ["https://apply.workable.com/Dreamdata/"],
                                "_names": {"workable_companies": {"apply.workable.com/dreamdata": "Dreamdata ApS"}}})

    assert len(postings) == 2 and {p["company"] for p in postings} == {"Dreamdata ApS"}


def test_the_keyword_search_keeps_the_job_s_own_company_even_with_followed_names(_robots_allows_api):
    _robots_allows_api.add(responses_lib.GET, workable._SEARCH_URL, body=_fx("search_page1.json"))

    postings = workable.scrape({**_CFG, "workable_companies": ["dreamdata"], "_mode": "search",
                                "_names": {"workable_companies": {"dreamdata": "Dreamdata ApS"}}})

    assert postings and "Dreamdata ApS" not in {p["company"] for p in postings}


def test_followed_accounts_drop_jobs_in_another_country_but_keep_remote_ones(_robots_allows_api):
    from door.scrapers import drain_non_local
    data = json.loads(_widget())
    data["jobs"][0].update(city="London", country="United Kingdom", telecommuting=False)
    data["jobs"][1].update(city="", country="", telecommuting=True)
    data["jobs"].append({**data["jobs"][0], "shortcode": "NEWBUD", "city": "Budapest", "country": "Hungary"})
    _robots_allows_api.add(responses_lib.GET, _WIDGET, body=json.dumps(data))
    drain_non_local("workable")

    postings = workable.scrape({"workable_companies": ["dreamdata"], "_mode": "collect", "location": "Budapest, Hungary"})

    assert sorted(p["platform_id"] for p in postings) == ["A3D8AC2227", "NEWBUD"]
    assert drain_non_local("workable") == 1


def test_the_keyword_search_records_no_non_local_drops(_robots_allows_api):
    from door.scrapers import drain_non_local
    _robots_allows_api.add(responses_lib.GET, _URL, body=_fx("search_page1.json"))
    _robots_allows_api.add(responses_lib.GET, _URL, body=_fx("search_page2.json"))
    drain_non_local("workable")

    workable.scrape({**_CFG, "_mode": "search", "location": "Budapest, Hungary"})

    assert drain_non_local("workable") == 0
