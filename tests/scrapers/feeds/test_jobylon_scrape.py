"""Fixture tests for the full Jobylon scrape() path: the company widget lists the jobs, each ad page
holds the text. HTTP is mocked with ``responses`` from saved real pages. No network access."""

from pathlib import Path

import pytest
import responses as responses_lib

from door.core.models import JobPosting
from door.scrapers import drain_errors, drain_non_local, drain_pushback
from door.scrapers.feeds import jobylon

_FIX = Path(__file__).parent / "fixtures" / "jobylon"

_WIDGET = "https://cdn.jobylon.com/jobs/companies/{}/embed/v2/"
_AD = "https://emp.jobylon.com/jobs/{}-{}/"
_LYKO = {
    "393911": "lyko-butikschef-till-lyko-marieberg",
    "391589": "lyko-crm-loyalty-manager",
    "393568": "lyko-assisterande-butikschef-till-lyko-kalmar",
}
_TEKNISKA = {"394181": "tekniska-verken-verksamhetsutvecklare", "393802": "tekniska-verken-produktspecialist"}


def _fx(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


def _mock_widget(company_id="2420", fixture="widget_2420.html", **kw):
    responses_lib.add(responses_lib.GET, _WIDGET.format(company_id), body=_fx(fixture), content_type="text/html; charset=utf-8", **kw)


def _mock_ads(ads: dict[str, str]):
    for job_id, slug in ads.items():
        # an ad is asked for by its id and answered with the page the site redirects to
        responses_lib.add(responses_lib.GET, f"https://emp.jobylon.com/jobs/{job_id}-{slug}/", body=_fx(f"job_{job_id}.html"),
                          content_type="text/html; charset=utf-8")


def _mock_lyko():
    _mock_widget()
    _mock_ads(_LYKO)


def _ad_requests():
    return [c.request.url for c in responses_lib.calls if "emp.jobylon.com" in c.request.url]


@responses_lib.activate
def test_scrape_maps_the_widget_and_the_ad_pages_into_postings():
    _mock_lyko()
    drain_errors()

    postings = jobylon.scrape({"jobylon_companies": ["2420"]})

    assert [p["platform_id"] for p in postings] == ["393911", "393568", "391589"]
    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "jobylon" and p["id"] == f"jobylon.{p['platform_id']}"
        assert p["company"] == "Lyko" and p["title"] and p["description"]
        assert p["url"].startswith("https://emp.jobylon.com/jobs/") and p["apply_url"] == p["url"]
        assert p["apply_type"] == "external" and p["posted_at"]
        assert "<" not in p["description"]
    by_id = {p["platform_id"]: p for p in postings}
    assert by_id["393911"]["location"] == "Örebro" and "butikschef" in by_id["393911"]["description"].lower()
    assert by_id["391589"]["title"] == "CRM & Loyalty Manager"  # an English ad and a local-language one both come through
    assert by_id["391589"]["description"].startswith("Every message")
    assert by_id["391589"]["posted_at"].startswith("2026-10-26")
    assert drain_errors() == {}


@responses_lib.activate
def test_known_ids_skip_their_ad_page():
    _mock_lyko()

    postings = jobylon.scrape({"jobylon_companies": ["2420"]}, known_ids=frozenset({"393911", "391589"}))

    assert [p["platform_id"] for p in postings] == ["393568"]
    assert _ad_requests() == [_AD.format("393568", _LYKO["393568"])]


@responses_lib.activate
def test_two_employers_are_read_side_by_side_and_a_job_is_kept_once():
    _mock_lyko()
    _mock_widget("1745", "widget_1745.html")
    _mock_ads(_TEKNISKA)

    postings = jobylon.scrape({"jobylon_companies": ["2420", "https://cdn.jobylon.com/jobs/companies/2420/embed/v2/", "1745"]})

    assert [p["platform_id"] for p in postings] == ["393911", "393568", "391589", "394181", "393802"]
    assert {p["company"] for p in postings} == {"Lyko", "Tekniska verken"}
    assert len({p["id"] for p in postings}) == 5


@responses_lib.activate
def test_the_followed_name_wins():
    _mock_lyko()

    postings = jobylon.scrape({"jobylon_companies": ["2420"], "_names": {"jobylon_companies": {"2420": "Lyko Group AB"}}})

    assert postings and {p["company"] for p in postings} == {"Lyko Group AB"}


@responses_lib.activate
def test_an_empty_board_returns_nothing_and_reports_zero(progress_events):
    responses_lib.add(responses_lib.GET, _WIDGET.format("2420"),
                      body="<script>JBL.embed_v2['jobs'] = [\n  \n ];\n</script>")
    drain_errors()

    assert jobylon.scrape({"jobylon_companies": ["2420"]}) == []
    assert any("0 results" in e.message for e in progress_events)
    assert drain_errors() == {}


@responses_lib.activate
def test_a_failed_widget_is_recorded_not_raised(progress_events):
    responses_lib.add(responses_lib.GET, _WIDGET.format("2420"), status=500)
    drain_errors()

    assert jobylon.scrape({"jobylon_companies": ["2420"]}) == []

    assert any("error fetching '2420'" in e.message for e in progress_events)
    assert "jobylon" in drain_errors()


@responses_lib.activate
def test_a_page_that_is_no_widget_is_an_error():
    responses_lib.add(responses_lib.GET, _WIDGET.format("2420"), body="<html>Login</html>")
    drain_errors()

    assert jobylon.scrape({"jobylon_companies": ["2420"]}) == []
    assert "jobylon" in drain_errors()


@responses_lib.activate
def test_an_ad_page_that_fails_leaves_that_job_for_the_next_run_and_is_recorded():
    _mock_widget()
    _mock_ads({k: v for k, v in _LYKO.items() if k != "391589"})
    responses_lib.add(responses_lib.GET, _AD.format("391589", _LYKO["391589"]), status=500)
    drain_errors()

    postings = jobylon.scrape({"jobylon_companies": ["2420"]})

    assert [p["platform_id"] for p in postings] == ["393911", "393568"]
    assert "jobylon" in drain_errors()


@responses_lib.activate
@pytest.mark.parametrize("status", [429, 403])
def test_pushback_is_recorded(status):
    responses_lib.add(responses_lib.GET, _WIDGET.format("2420"), status=status)
    drain_errors()
    drain_pushback("jobylon")

    assert jobylon.scrape({"jobylon_companies": ["2420"]}) == []

    assert drain_pushback("jobylon") is True
    assert "jobylon" in drain_errors()


@responses_lib.activate
def test_postings_in_another_country_are_dropped_and_counted():
    _mock_lyko()
    drain_non_local("jobylon")
    # one ad is in Budapest
    page = _fx("widget_2420.html").replace("locations_text: 'Örebro'", "locations_text: 'Budapest'")
    responses_lib.replace(responses_lib.GET, _WIDGET.format("2420"), body=page, content_type="text/html; charset=utf-8")

    postings = jobylon.scrape({"jobylon_companies": ["2420"], "location": "Stockholm, Sweden"})

    assert [p["platform_id"] for p in postings] == ["393568", "391589"]
    assert drain_non_local("jobylon") == 1


# --------------------------------------------------------------------------- #
# probe (issue #178)
# --------------------------------------------------------------------------- #

_PROBE_CFG = {"jobylon_companies": ["2420", "1745"]}


@responses_lib.activate
def test_probe_ok_makes_one_request_for_the_first_employer():
    body = _fx("widget_2420.html")
    responses_lib.add(responses_lib.GET, _WIDGET.format("2420"), body=body)
    drain_errors()

    result = jobylon.probe(_PROBE_CFG)

    assert result["structure_ok"] is True and result["ext"] == "html" and result["raw"] == body
    assert [p["platform_id"] for p in result["postings"]] == ["393911", "393568", "391589"]
    for p in result["postings"]:
        JobPosting.model_validate(p)
    assert [c.request.url for c in responses_lib.calls if "robots" not in c.request.url] == [_WIDGET.format("2420")]
    assert drain_errors() == {}


@responses_lib.activate
def test_probe_drift_when_the_job_list_is_gone():
    responses_lib.add(responses_lib.GET, _WIDGET.format("2420"),
                      body=_fx("widget_2420.html").replace("JBL.embed_v2['jobs']", "JBL.embed_v2['other']"))

    result = jobylon.probe(_PROBE_CFG)

    assert result["structure_ok"] is False and result["reason"]
    assert not result.get("wall") and not result.get("unreachable")


@responses_lib.activate
def test_probe_wall_and_unreachable():
    responses_lib.add(responses_lib.GET, _WIDGET.format("2420"), status=403)
    assert jobylon.probe(_PROBE_CFG)["wall"] is True

    responses_lib.reset()
    import requests
    responses_lib.add(responses_lib.GET, _WIDGET.format("2420"), body=requests.ConnectionError("down"))
    assert jobylon.probe(_PROBE_CFG)["unreachable"] is True
    assert drain_errors() == {}


def test_probe_without_employers_is_none():
    assert jobylon.probe({}) is None
