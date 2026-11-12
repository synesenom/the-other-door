"""Fixture tests for Beetween: Giboire's career site (``giboire.nous-recrutons.fr``), its WordPress job list and ad
pages as served, trimmed and their text rewritten."""

import re

import pytest
import requests
import responses

from door.core.models import JobPosting
from door.scrapers import drain_errors, drain_non_local, drain_pushback
from door.scrapers.feeds import beetween
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "beetween"
_HOST = "https://giboire.nous-recrutons.fr"
_API = re.compile(re.escape(_HOST) + r"/wp-json/wp/v2/job\?.*")
_ADS = {"2080": "0iwubmg1rl", "2079": "0alwstmu28", "2078": "itvu98wqf6", "2077": "lxhlaye9yh"}
_SLUGS = {
    "0iwubmg1rl": "responsable-developpement-bouches-du-rhone-var", "0alwstmu28": "comptable-de-copropriete-fh",
    "itvu98wqf6": "assistante-commerciale-fh", "lxhlaye9yh": "comptable-de-copropriete-fh",
}
_PIDS = [f"giboire.nous-recrutons.fr-{i}" for i in _ADS]


def _fx(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


def _ad_url(key: str) -> str:
    return f"{_HOST}/poste/{key}-{_SLUGS[key]}/"


def _add_list(*, status=200, pages=2):
    """The job list as two pages of two; the real answer says how many pages there are in a header."""
    for page in (1, 2):
        responses.add(responses.GET, re.compile(re.escape(_HOST) + rf"/wp-json/wp/v2/job\?.*\bpage={page}\b.*"),
                      body=_fx(f"giboire_jobs_p{page}.json"), status=status,
                      headers={"X-WP-Total": "4", "X-WP-TotalPages": str(pages)})


def _add_ads(keys=None):
    for key in keys or _SLUGS:
        responses.add(responses.GET, _ad_url(key), body=_fx(f"giboire_ad_{key}.html"))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


@responses.activate
def test_scrape_pages_through_the_list_and_maps_every_job():
    _add_list()
    _add_ads()

    postings = beetween.scrape({"beetween_companies": ["giboire"]})

    assert [p["platform_id"] for p in postings] == _PIDS
    first = postings[0]
    JobPosting.model_validate(first)
    assert first["id"] == "beetween.giboire-nous-recrutons-fr-2080"
    assert first["title"] == "Responsable Développement Bouches du Rhône & Var"
    assert first["company"] == "GROUPE GIBOIRE"
    assert first["location"] == "Marseille, France"
    assert first["url"] == _ad_url("0iwubmg1rl") and first["apply_url"] == first["url"]
    assert first["posted_at"].startswith("2026-10-28")
    assert "Prospection foncière" in first["description"] and "<" not in first["description"]
    assert first["source"] == "beetween"
    assert len(responses.calls) == 6  # two list pages and four ads


@responses.activate
def test_the_list_is_asked_for_by_pages_of_fifty():
    _add_list()
    _add_ads()

    beetween.scrape({"beetween_companies": ["giboire"]})

    urls = [c.request.url for c in responses.calls if "wp-json" in c.request.url]
    assert len(urls) == 2 and all("per_page=50" in u for u in urls)
    assert "page=1" in urls[0] and "page=2" in urls[1]


@responses.activate
def test_a_single_page_list_is_one_request():
    responses.add(responses.GET, _API, body=_fx("giboire_jobs_p1.json"), headers={"X-WP-TotalPages": "1"})
    _add_ads(["0iwubmg1rl", "0alwstmu28"])

    postings = beetween.scrape({"beetween_companies": ["giboire"]})

    assert len(postings) == 2
    assert len([c for c in responses.calls if "wp-json" in c.request.url]) == 1


@responses.activate
def test_known_ids_skip_the_ad_requests():
    _add_list()
    _add_ads(["itvu98wqf6", "lxhlaye9yh"])

    postings = beetween.scrape({"beetween_companies": ["giboire"]}, known_ids=frozenset(_PIDS[:2]))

    assert [p["platform_id"] for p in postings] == _PIDS[2:]
    assert len(responses.calls) == 4


@responses.activate
def test_the_followed_name_wins():
    _add_list()
    _add_ads()

    postings = beetween.scrape({"beetween_companies": ["giboire"],
                                "_names": {"beetween_companies": {"giboire": "Giboire"}}})

    assert {p["company"] for p in postings} == {"Giboire"}


@responses.activate
def test_an_entry_on_the_employers_own_host_is_read_there():
    own = "https://recrutement.clermontmetropole.eu"
    responses.add(responses.GET, re.compile(re.escape(own) + r"/wp-json/wp/v2/job\?.*"),
                  body=_fx("giboire_jobs_p1.json").replace(_HOST.replace("/", r"\/"), own.replace("/", r"\/")),
                  headers={"X-WP-TotalPages": "1"})
    for key in ("0iwubmg1rl", "0alwstmu28"):
        responses.add(responses.GET, f"{own}/poste/{key}-{_SLUGS[key]}/", body=_fx(f"giboire_ad_{key}.html"))

    postings = beetween.scrape({"beetween_companies": ["recrutement.clermontmetropole.eu"]})

    assert [p["platform_id"] for p in postings] == ["recrutement.clermontmetropole.eu-2080",
                                                   "recrutement.clermontmetropole.eu-2079"]
    assert postings[0]["url"].startswith(own + "/poste/")


@responses.activate
def test_the_same_job_listed_by_two_entries_comes_once():
    _add_list()
    _add_ads()
    responses.add(responses.GET, re.compile(r"https://giboire\.nous-recrutons\.fr/wp-json/wp/v2/job\?.*"),
                  body=_fx("giboire_jobs_p1.json"), headers={"X-WP-TotalPages": "1"})

    postings = beetween.scrape({"beetween_companies": ["giboire", "giboire.nous-recrutons.fr"]})

    assert [p["platform_id"] for p in postings] == _PIDS


@responses.activate
def test_a_failing_list_is_a_recorded_error():
    responses.add(responses.GET, re.compile(r"https://bad\.nous-recrutons\.fr/wp-json/.*"), status=500)
    _add_list()
    _add_ads()

    drain_errors()
    assert len(beetween.scrape({"beetween_companies": ["bad", "giboire"]})) == 4
    assert "bad" in drain_errors()["beetween"][0]


@responses.activate
def test_a_site_that_is_no_wordpress_job_list_is_a_recorded_error_not_an_empty_board():
    responses.add(responses.GET, _API, body="<html>Page non trouvée</html>")

    drain_errors()
    assert beetween.scrape({"beetween_companies": ["giboire"]}) == []
    assert "giboire" in drain_errors()["beetween"][0]


@responses.activate
def test_a_failing_ad_is_recorded_and_the_others_kept():
    _add_list()
    responses.add(responses.GET, _ad_url("0iwubmg1rl"), status=500)
    responses.add(responses.GET, _ad_url("0alwstmu28"), body=_fx("giboire_ad_0alwstmu28.html"))
    responses.add(responses.GET, _ad_url("itvu98wqf6"), body="<html>no ad</html>")
    responses.add(responses.GET, _ad_url("lxhlaye9yh"), body=_fx("giboire_ad_lxhlaye9yh.html"))

    drain_errors()
    postings = beetween.scrape({"beetween_companies": ["giboire"]})

    assert [p["platform_id"] for p in postings] == [_PIDS[1], _PIDS[3]]
    assert len(drain_errors()["beetween"]) == 2


@responses.activate
@pytest.mark.parametrize("status", [429, 403])
def test_pushback_is_recorded_and_stops_the_board(status):
    responses.add(responses.GET, _API, status=status)

    drain_errors()
    drain_pushback("beetween")
    assert beetween.scrape({"beetween_companies": ["giboire"]}) == []

    assert drain_pushback("beetween") is True
    assert drain_errors()["beetween"]


@responses.activate
def test_pushback_on_an_ad_stops_the_rest_of_the_board():
    _add_list()
    responses.add(responses.GET, _ad_url("0iwubmg1rl"), status=429)

    drain_pushback("beetween")
    beetween.scrape({"beetween_companies": ["giboire"]})

    assert drain_pushback("beetween") is True
    assert [c.request.url for c in responses.calls].count(_ad_url("0alwstmu28")) == 0


@responses.activate
def test_a_posting_in_another_country_is_dropped():
    _add_list()
    _add_ads()
    responses.replace(responses.GET, _ad_url("0alwstmu28"),
                      body=_fx("giboire_ad_0alwstmu28.html").replace('"addressLocality": "Rennes", "addressRegion": "France"',
                                                                     '"addressLocality": "Berlin", "addressRegion": "Germany"'))

    drain_non_local("beetween")
    postings = beetween.scrape({"beetween_companies": ["giboire"], "location": "Paris", "_country": "fr"})

    assert _PIDS[1] not in {p["platform_id"] for p in postings}
    assert len(postings) == 3 and drain_non_local("beetween") == 1


def test_scrape_without_entries_is_empty():
    assert beetween.scrape({}) == []
    assert beetween.probe({}) is None


# --- probe ---

@responses.activate
def test_probe_reads_the_first_list_page_only():
    responses.add(responses.GET, _API, body=_fx("giboire_jobs_p1.json"), headers={"X-WP-TotalPages": "2"})

    drain_errors()
    result = beetween.probe({"beetween_companies": ["giboire"]})

    assert result["structure_ok"] is True and len(result["postings"]) == 2
    assert len(responses.calls) == 1
    assert drain_errors() == {}


@responses.activate
def test_probe_of_a_site_without_open_jobs_is_still_a_list():
    responses.add(responses.GET, _API, body="[]")

    result = beetween.probe({"beetween_companies": ["giboire"]})

    assert result["structure_ok"] is True and result["postings"] == []


@responses.activate
def test_probe_of_a_page_that_is_no_job_list_has_no_structure():
    responses.add(responses.GET, _API, body='{"code": "rest_no_route", "message": "Aucune route"}')

    result = beetween.probe({"beetween_companies": ["giboire"]})

    assert result["structure_ok"] is False and result["reason"]


@responses.activate
def test_probe_connection_error_is_unreachable():
    responses.add(responses.GET, _API, body=requests.ConnectionError("down"))

    result = beetween.probe({"beetween_companies": ["giboire"]})

    assert result.get("unreachable") and result["structure_ok"] is False


@responses.activate
def test_probe_403_is_a_wall():
    responses.add(responses.GET, _API, status=403)

    assert beetween.probe({"beetween_companies": ["giboire"]}).get("wall")
