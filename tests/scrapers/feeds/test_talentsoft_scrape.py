"""Fixture tests for Talentsoft (issue #559): AGRICA's list pages, RSS feed and one ad page, trimmed and rewritten."""

import pytest
import requests
import responses

from door.core.models import JobPosting
from door.scrapers import drain_errors, drain_non_local, drain_pushback
from door.scrapers.feeds import talentsoft
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "talentsoft"
_HOST = "https://agrica-career.talent-soft.com"
_LIST = f"{_HOST}/offre-de-emploi/liste-offres.aspx"
_RSS = f"{_HOST}/handlers/offerRss.ashx"
_AD_2269 = f"{_HOST}/offre-de-emploi/emploi-assistant-business-analyst-stage-h-f_2269.aspx"
_PAGE_1 = responses.matchers.query_param_matcher({})
_PAGE_2 = responses.matchers.query_param_matcher({"page": "2"})
_CFG = {"talentsoft_hosts": ["agrica-career.talent-soft.com"]}


def _read(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


def _serve(rss: str | None = None):
    responses.add(responses.GET, _LIST, body=_read("agrica_list_1.html"), match=[_PAGE_1])
    responses.add(responses.GET, _LIST, body=_read("agrica_list_2.html"), match=[_PAGE_2])
    responses.add(responses.GET, _RSS, body=rss if rss is not None else _read("agrica_rss.xml"))
    responses.add(responses.GET, _AD_2269, body=_read("agrica_ad_2269.html"))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


def _urls():
    return [c.request.url for c in responses.calls]


@responses.activate
def test_scrape_pages_the_list_and_takes_the_text_from_the_feed_or_the_ad_page():
    _serve()

    postings = talentsoft.scrape(_CFG)

    assert [p["platform_id"] for p in postings] == [
        "agrica-career.talent-soft.com-2287", "agrica-career.talent-soft.com-2286",
        "agrica-career.talent-soft.com-2281", "agrica-career.talent-soft.com-2270",
        "agrica-career.talent-soft.com-2269"]
    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "talentsoft" and p["company"] == "AGRICA"
        assert p["description"] and "<" not in p["description"]
    first, last = postings[0], postings[-1]
    assert first["id"] == "talentsoft.agrica-career-talent-soft-com-2287"
    assert first["title"] == "COMPTABLE TECHNIQUE ASSURANCE H/F"
    assert first["location"] == "Paris (75)"
    assert first["url"] == f"{_HOST}/offre-de-emploi/emploi-comptable-technique-assurance-h-f_2287.aspx"
    assert first["apply_url"] == first["url"]
    assert first["posted_at"].startswith("2026-10-30T23:30:14")   # the feed's precise time
    assert "rapprochements bancaires" in first["description"]
    assert last["title"] == "ASSISTANT BUSINESS ANALYST - Stage H/F"
    assert last["posted_at"].startswith("2026-10-09")             # the list's day
    assert "user stories" in last["description"]
    # list pages 1 and 2, the feed once, and the one ad the feed (capped at 20) does not hold
    assert len(responses.calls) == 4 and _urls()[-1] == _AD_2269


@responses.activate
def test_known_ids_skip_the_ad_page_and_the_ad():
    _serve()
    known = frozenset({"agrica-career.talent-soft.com-2269", "agrica-career.talent-soft.com-2286"})

    postings = talentsoft.scrape(_CFG, known)

    assert {p["title"] for p in postings}.isdisjoint({"ASSISTANT BUSINESS ANALYST - Stage H/F", "ANALYSTE DATA H/F"})
    assert len(postings) == 3 and _AD_2269 not in _urls()


@responses.activate
def test_the_followed_name_wins():
    _serve()

    postings = talentsoft.scrape({**_CFG, "_names": {"talentsoft_hosts": {"agrica-career.talent-soft.com": "Agrica Groupe"}}})

    assert {p["company"] for p in postings} == {"Agrica Groupe"}


@responses.activate
def test_a_page_beyond_the_last_repeating_the_first_ends_the_walk():
    page_1 = _read("agrica_list_1.html").replace("5 offre(s)", "9 offre(s)")
    responses.add(responses.GET, _LIST, body=page_1, match=[_PAGE_1])
    responses.add(responses.GET, _LIST, body=page_1, match=[_PAGE_2])
    responses.add(responses.GET, _RSS, body=_read("agrica_rss.xml"))

    postings = talentsoft.scrape(_CFG)

    assert len(postings) == 3
    assert len([u for u in _urls() if "liste-offres" in u]) == 2   # page 1, then page 2 that repeats it


@responses.activate
def test_a_feed_that_fails_costs_one_ad_page_per_ad_and_is_recorded():
    _serve()
    responses.replace(responses.GET, _RSS, status=500)
    for slug_id in ("comptable-technique-assurance-h-f_2287", "analyste-data-h-f_2286",
                    "conseiller-gestion-retraite-complementaire-f-h-h-f_2281",
                    "responsable-projets-parcours-et-experience-clients-h-f_2270"):
        responses.add(responses.GET, f"{_HOST}/offre-de-emploi/emploi-{slug_id}.aspx",
                      body=_read("agrica_ad_2269.html"))
    drain_errors()

    postings = talentsoft.scrape(_CFG)

    assert len(postings) == 5 and all(p["description"] for p in postings)
    assert any("feed" in e for e in drain_errors()["talentsoft"])


@responses.activate
def test_an_ad_page_that_fails_is_recorded_and_the_rest_go_on():
    _serve()
    responses.replace(responses.GET, _AD_2269, status=500)
    drain_errors()

    postings = talentsoft.scrape(_CFG)

    assert len(postings) == 4
    assert any("2269" in e for e in drain_errors()["talentsoft"])


@responses.activate
def test_a_failed_list_is_a_recorded_error_not_a_raise():
    responses.add(responses.GET, _LIST, status=500)
    drain_errors()

    assert talentsoft.scrape(_CFG) == []
    assert drain_errors()["talentsoft"]


@responses.activate
def test_a_refusal_is_pushback_and_ends_the_board():
    responses.add(responses.GET, _LIST, status=403)
    drain_errors()
    drain_pushback("talentsoft")

    assert talentsoft.scrape(_CFG) == []
    assert drain_pushback("talentsoft") is True
    assert drain_errors()["talentsoft"]


@responses.activate
def test_a_page_that_is_not_the_list_is_a_recorded_error():
    responses.add(responses.GET, _LIST, body="<html><title>Maintenance</title></html>")
    drain_errors()

    assert talentsoft.scrape(_CFG) == []
    assert drain_errors()["talentsoft"]


@responses.activate
def test_scrape_drops_ads_in_another_country():
    _serve()
    responses.replace(responses.GET, _LIST, body=_read("agrica_list_1.html").replace("Paris (75)", "Vienna, Austria"),
                      match=[_PAGE_1])
    drain_non_local("talentsoft")

    postings = talentsoft.scrape({**_CFG, "location": "Paris, France"})

    assert len(postings) == 2    # 2270 and 2269 are in Paris; the three of page 1 are not
    assert drain_non_local("talentsoft") == 3


def test_no_hosts_no_request():
    assert talentsoft.scrape({}) == []
    assert talentsoft.probe({}) is None


@responses.activate
def test_probe_reads_the_first_list_page_with_one_request():
    responses.add(responses.GET, _LIST, body=_read("agrica_list_1.html"))
    drain_errors()

    result = talentsoft.probe({"talentsoft_hosts": ["agrica-career.talent-soft.com", "other.talent-soft.com"]})

    assert result["structure_ok"] is True and len(result["postings"]) == 3
    assert len(responses.calls) == 1
    assert drain_errors() == {}


@responses.activate
def test_probe_drift_without_cards():
    responses.add(responses.GET, _LIST, body=_read("agrica_list_1.html").replace("ts-offer-card__title-link", "x"))

    result = talentsoft.probe(_CFG)

    assert result["structure_ok"] is False and result["reason"]


@responses.activate
def test_probe_unreachable_and_wall():
    responses.add(responses.GET, _LIST, body=requests.ConnectionError("down"))
    down = talentsoft.probe(_CFG)
    assert down["structure_ok"] is False and down.get("unreachable") is True
    responses.replace(responses.GET, _LIST, status=403)
    walled = talentsoft.probe(_CFG)
    assert walled["structure_ok"] is False and walled.get("wall") is True
