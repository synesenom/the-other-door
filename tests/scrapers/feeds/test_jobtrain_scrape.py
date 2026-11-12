"""Fixture tests for Jobtrain: the Leigh Academies Trust list (a tenant on the shared host) and Crisis's (its own host),
real logged-out answers, trimmed and their text rewritten. The site has only English ads."""

import pytest
import requests
import responses

from door.core.models import JobPosting
from door.scrapers import drain_errors, drain_non_local, drain_pushback
from door.scrapers.feeds import jobtrain
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "jobtrain"
_LAT = "https://www.jobtrain.co.uk/leighacademiestrust"
_CRISIS = "https://jobs.crisis.org.uk"
_LAT_IDS = ["9610", "9609", "9600", "9592"]


def _fx(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


def _list(base: str, skip: int) -> str:
    return f"{base}/Home/_JobCard?Skip={skip}"


def _ad(base: str, jid: str) -> str:
    return f"{base}/Job/JobDetail?JobId={jid}"


def _mock_lat(ads: tuple[str, ...] = tuple(_LAT_IDS)):
    responses.add(responses.GET, _list(_LAT, 0), body=_fx("lat_cards_1.html"))
    responses.add(responses.GET, _list(_LAT, 3), body=_fx("lat_cards_2.html"))
    for jid in ads:
        responses.add(responses.GET, _ad(_LAT, jid), body=_fx(f"lat_{jid}.html"))


def _mock_crisis():
    responses.add(responses.GET, _list(_CRISIS, 0), body=_fx("crisis_cards.html"))
    for jid in ("11924", "11906"):
        responses.add(responses.GET, _ad(_CRISIS, jid), body=_fx(f"crisis_{jid}.html"))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


@responses.activate
def test_scrape_pages_through_the_list_and_maps_every_ad_with_its_text():
    _mock_lat()

    postings = jobtrain.scrape({"jobtrain_companies": ["leighacademiestrust"]})

    assert [p["platform_id"] for p in postings] == [f"leighacademiestrust-{i}" for i in _LAT_IDS]
    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "jobtrain" and p["company"] == "LeighAcademiesTrust"
        assert p["description"] and "<" not in p["description"]
        assert p["url"].startswith(f"{_LAT}/Job/JobDetail?JobId=") and "Source=" not in p["url"]
    exams = postings[0]
    assert exams["id"] == "jobtrain.leighacademiestrust-9610"
    assert exams["title"] == "Exams Officer" and exams["location"] == "Hartley, Kent, GB"
    assert exams["posted_at"].startswith("2026-11-03")
    assert exams["description"].startswith("Competitive salary with progression opportunities")
    assert postings[3]["title"] == "People Advisor (HR)" and postings[3]["posted_at"].startswith("2026-10-21")
    assert len(responses.calls) == 6   # two list pages, then one ad each


@responses.activate
def test_known_ids_skip_the_ad_requests():
    _mock_lat(("9592",))

    postings = jobtrain.scrape({"jobtrain_companies": ["leighacademiestrust"]},
                               known_ids=frozenset({"leighacademiestrust-9610", "leighacademiestrust-9609", "leighacademiestrust-9600"}))

    assert [p["platform_id"] for p in postings] == ["leighacademiestrust-9592"]
    assert len(responses.calls) == 3


@responses.activate
def test_a_custom_host_is_read_from_its_own_host():
    _mock_crisis()

    postings = jobtrain.scrape({"jobtrain_companies": ["jobs.crisis.org.uk"]})

    assert [p["title"] for p in postings] == ["Data Insight Analyst", "Prospect Research Manager"]
    assert {p["company"] for p in postings} == {"Crisis"}
    assert postings[0]["url"] == f"{_CRISIS}/Job/JobDetail?JobId=11924"
    assert postings[0]["platform_id"] == "jobs.crisis.org.uk-11924"
    assert len(responses.calls) == 3   # one list page (the total is reached), then the two ads


@responses.activate
def test_the_followed_name_wins():
    _mock_crisis()

    postings = jobtrain.scrape({"jobtrain_companies": ["jobs.crisis.org.uk"], "_names": {"jobtrain_companies": {"jobs.crisis.org.uk": "Crisis UK"}}})

    assert {p["company"] for p in postings} == {"Crisis UK"}


@responses.activate
def test_two_entries_for_one_tenant_give_its_ads_once():
    _mock_lat()

    postings = jobtrain.scrape({"jobtrain_companies": ["leighacademiestrust", f"{_LAT}/Home/Job"]})

    assert [p["platform_id"] for p in postings] == [f"leighacademiestrust-{i}" for i in _LAT_IDS]


@responses.activate
def test_a_failing_list_is_a_recorded_error_and_the_other_tenant_is_kept():
    responses.add(responses.GET, _list("https://www.jobtrain.co.uk/gone", 0), status=404)
    _mock_crisis()

    drain_errors()
    assert len(jobtrain.scrape({"jobtrain_companies": ["gone", "jobs.crisis.org.uk"]})) == 2
    assert "gone" in drain_errors()["jobtrain"][0]


@responses.activate
def test_a_page_that_is_no_list_is_a_recorded_error_not_an_empty_board():
    responses.add(responses.GET, _list(_LAT, 0), body="<html><h1>Sorry</h1></html>")

    drain_errors()
    assert jobtrain.scrape({"jobtrain_companies": ["leighacademiestrust"]}) == []
    assert "leighacademiestrust" in drain_errors()["jobtrain"][0]


@responses.activate
def test_a_tenant_without_open_jobs_is_quiet():
    responses.add(responses.GET, _list(_LAT, 0), body='<input id="totalCurrentRecords" value="0"><input id="totalMatchRecords" value="0">')

    drain_errors()
    assert jobtrain.scrape({"jobtrain_companies": ["leighacademiestrust"]}) == []
    assert drain_errors() == {}


@responses.activate
def test_a_failing_ad_is_recorded_and_the_others_kept():
    responses.add(responses.GET, _list(_LAT, 0), body=_fx("lat_cards_1.html"))
    responses.add(responses.GET, _list(_LAT, 3), body=_fx("lat_cards_2.html"))
    responses.add(responses.GET, _ad(_LAT, "9610"), status=500)
    responses.add(responses.GET, _ad(_LAT, "9609"), body="<html>Job not found</html>")
    responses.add(responses.GET, _ad(_LAT, "9600"), body=_fx("lat_9600.html"))
    responses.add(responses.GET, _ad(_LAT, "9592"), body=_fx("lat_9592.html"))

    drain_errors()
    postings = jobtrain.scrape({"jobtrain_companies": ["leighacademiestrust"]})

    assert [p["platform_id"] for p in postings] == ["leighacademiestrust-9600", "leighacademiestrust-9592"]
    assert len(drain_errors()["jobtrain"]) == 2


@responses.activate
@pytest.mark.parametrize("status", [429, 403])
def test_pushback_on_the_list_is_recorded_and_stops_the_tenant(status):
    responses.add(responses.GET, _list(_LAT, 0), status=status)

    drain_errors()
    drain_pushback("jobtrain")
    assert jobtrain.scrape({"jobtrain_companies": ["leighacademiestrust"]}) == []

    assert drain_pushback("jobtrain") is True
    assert drain_errors()["jobtrain"]


@responses.activate
def test_pushback_on_an_ad_stops_the_rest_of_the_tenant():
    responses.add(responses.GET, _list(_LAT, 0), body=_fx("lat_cards_1.html"))
    responses.add(responses.GET, _list(_LAT, 3), body=_fx("lat_cards_2.html"))
    responses.add(responses.GET, _ad(_LAT, "9610"), status=429)

    drain_pushback("jobtrain")
    jobtrain.scrape({"jobtrain_companies": ["leighacademiestrust"]})

    assert drain_pushback("jobtrain") is True
    assert [c.request.url for c in responses.calls].count(_ad(_LAT, "9609")) == 0


@responses.activate
def test_a_list_that_keeps_repeating_its_first_page_ends():
    for skip in (0, 3, 6, 9):
        responses.add(responses.GET, _list(_LAT, skip), body=_fx("lat_cards_1.html").replace('value="4"', 'value="400"'))
    for jid in ("9610", "9609", "9600"):
        responses.add(responses.GET, _ad(_LAT, jid), body=_fx(f"lat_{jid}.html"))

    postings = jobtrain.scrape({"jobtrain_companies": ["leighacademiestrust"]})

    assert len(postings) == 3
    assert len(responses.calls) == 2 + 3   # the repeated page ends the paging


@responses.activate
def test_a_posting_in_another_country_is_dropped():
    _mock_lat()

    drain_non_local("jobtrain")
    postings = jobtrain.scrape({"jobtrain_companies": ["leighacademiestrust"], "location": "Copenhagen", "_country": "dk"})

    assert postings == []
    assert drain_non_local("jobtrain") == 4


def test_scrape_without_entries_is_empty():
    assert jobtrain.scrape({}) == []
    assert jobtrain.probe({}) is None


# --- probe ---

@responses.activate
def test_probe_reads_the_first_list_page_only():
    responses.add(responses.GET, _list(_LAT, 0), body=_fx("lat_cards_1.html"))

    drain_errors()
    result = jobtrain.probe({"jobtrain_companies": ["leighacademiestrust"]})

    assert result["structure_ok"] is True and len(result["postings"]) == 3
    assert len(responses.calls) == 1
    assert drain_errors() == {}


@responses.activate
def test_probe_of_a_page_without_its_job_block_has_no_structure():
    responses.add(responses.GET, _list(_LAT, 0), body=_fx("lat_cards_1.html").split('<div tabindex="-1" class="card')[0].replace("totalMatchRecords", "x"))

    result = jobtrain.probe({"jobtrain_companies": ["leighacademiestrust"]})

    assert result["structure_ok"] is False and result["reason"]


@responses.activate
def test_probe_connection_error_is_unreachable():
    responses.add(responses.GET, _list(_LAT, 0), body=requests.ConnectionError("down"))

    result = jobtrain.probe({"jobtrain_companies": ["leighacademiestrust"]})

    assert result.get("unreachable") and result["structure_ok"] is False


@responses.activate
@pytest.mark.parametrize("status", [401, 403])
def test_probe_401_and_403_are_a_wall(status):
    responses.add(responses.GET, _list(_LAT, 0), status=status)

    assert jobtrain.probe({"jobtrain_companies": ["leighacademiestrust"]}).get("wall")
