"""Fixture tests for Taleez: Donecle's live job list and ads (Toulouse), trimmed and their text rewritten."""

import json

import pytest
import requests
import responses

from door.core.models import JobPosting
from door.scrapers import drain_errors, drain_non_local, drain_pushback
from door.scrapers.feeds import taleez
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "taleez"
_LIST = "https://donecle.taleez.com/api/careez"
_IDS = ["600922", "600692", "598975"]
_SLUGS = {
    "600922": "responsable-rh-h-f-toulouse-donecle-cdi",
    "600692": "international-key-account-manager-toulouse-donecle-cdi",
    "598975": "stage-ingenieur-e-ml-evaluation-des-performances-et-validation-des-modeles-toulouse-donecle",
}


def _fx(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


def _ad_url(jid: str) -> str:
    return f"https://taleez.com/apply/{_SLUGS[jid]}"


def _mock_all(listing: str | None = None):
    responses.add(responses.GET, _LIST, body=listing or _fx("donecle_careez.json"), content_type="application/json")
    for jid in _IDS:
        responses.add(responses.GET, _ad_url(jid), body=_fx(f"ad_{jid}.html"))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


@responses.activate
def test_scrape_maps_every_listed_job_with_its_text():
    _mock_all()

    postings = taleez.scrape({"taleez_companies": ["donecle"]})

    assert [p["platform_id"] for p in postings] == _IDS
    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "taleez" and p["company"] == "Donecle" and p["location"] == "Toulouse, FR"
        assert p["description"] and "<" not in p["description"]
    french, english, internship = postings
    assert french["id"] == "taleez.600922"
    assert french["title"] == "Responsable RH (H/F)"
    assert french["url"] == _ad_url("600922") and french["apply_url"] == french["url"]
    assert french["posted_at"].startswith("2026-10-12T10:17:16")
    assert french["description"].startswith("Rattaché(e) à la direction") and "Bac+5" in french["description"]
    assert english["title"] == "Key Account Manager"
    assert english["description"].startswith("We are looking for a proactive Key Account Manager")
    assert internship["title"].startswith("Stage Ingénieur")
    assert len(responses.calls) == 4   # the list, then one ad each


@responses.activate
def test_known_ids_skip_the_ad_requests_but_not_the_postings_of_the_list():
    responses.add(responses.GET, _LIST, body=_fx("donecle_careez.json"))
    responses.add(responses.GET, _ad_url("598975"), body=_fx("ad_598975.html"))

    postings = taleez.scrape({"taleez_companies": ["donecle"]}, known_ids=frozenset({"600922", "600692"}))

    assert [p["platform_id"] for p in postings] == ["598975"]
    assert len(responses.calls) == 2


@responses.activate
def test_the_followed_name_wins():
    _mock_all()

    postings = taleez.scrape({"taleez_companies": ["donecle"], "_names": {"taleez_companies": {"donecle": "Donecle SAS"}}})

    assert {p["company"] for p in postings} == {"Donecle SAS"}


@responses.activate
def test_a_link_as_the_entry_is_read_from_its_tenant():
    _mock_all()

    postings = taleez.scrape({"taleez_companies": ["https://donecle.taleez.com/en"]})

    assert len(postings) == 3


@responses.activate
def test_the_same_job_listed_by_two_entries_comes_once():
    _mock_all()

    postings = taleez.scrape({"taleez_companies": ["donecle", "donecle.taleez.com"]})

    assert [p["platform_id"] for p in postings] == _IDS


@responses.activate
def test_a_failing_list_is_a_recorded_error_and_the_other_board_is_kept():
    responses.add(responses.GET, "https://bad.taleez.com/api/careez", status=500)
    _mock_all()

    drain_errors()
    assert len(taleez.scrape({"taleez_companies": ["bad", "donecle"]})) == 3
    assert "bad" in drain_errors()["taleez"][0]


@responses.activate
def test_a_tenant_that_does_not_exist_is_a_recorded_error_not_an_empty_board():
    responses.add(responses.GET, "https://gone.taleez.com/api/careez", body="<html>Erreur</html>")

    drain_errors()
    assert taleez.scrape({"taleez_companies": ["gone"]}) == []
    assert "gone" in drain_errors()["taleez"][0]


@responses.activate
def test_a_tenant_without_open_jobs_is_quiet():
    responses.add(responses.GET, _LIST, body=json.dumps({"name": "Donecle", "jobs": []}))

    drain_errors()
    assert taleez.scrape({"taleez_companies": ["donecle"]}) == []
    assert drain_errors() == {}


@responses.activate
def test_a_failing_ad_is_recorded_and_the_others_kept():
    responses.add(responses.GET, _LIST, body=_fx("donecle_careez.json"))
    responses.add(responses.GET, _ad_url("600922"), status=500)
    responses.add(responses.GET, _ad_url("600692"), body=_fx("ad_600692.html"))
    responses.add(responses.GET, _ad_url("598975"), body="<html>no ad</html>")

    drain_errors()
    postings = taleez.scrape({"taleez_companies": ["donecle"]})

    assert [p["platform_id"] for p in postings] == ["600692"]
    assert len(drain_errors()["taleez"]) == 2


@responses.activate
@pytest.mark.parametrize("status", [429, 403])
def test_pushback_on_the_list_is_recorded_and_stops_the_board(status):
    responses.add(responses.GET, _LIST, status=status)

    drain_errors()
    drain_pushback("taleez")
    assert taleez.scrape({"taleez_companies": ["donecle"]}) == []

    assert drain_pushback("taleez") is True
    assert drain_errors()["taleez"]


@responses.activate
def test_pushback_on_an_ad_stops_the_rest_of_the_board():
    responses.add(responses.GET, _LIST, body=_fx("donecle_careez.json"))
    responses.add(responses.GET, _ad_url("600922"), status=429)

    drain_pushback("taleez")
    taleez.scrape({"taleez_companies": ["donecle"]})

    assert drain_pushback("taleez") is True
    assert [c.request.url for c in responses.calls].count(_ad_url("600692")) == 0


@responses.activate
def test_a_posting_in_another_country_is_dropped():
    data = json.loads(_fx("donecle_careez.json"))
    data["jobs"][1]["location"] = {"city": "Berlin", "country": "DE"}
    _mock_all(json.dumps(data))

    drain_non_local("taleez")
    postings = taleez.scrape({"taleez_companies": ["donecle"], "location": "Paris", "_country": "fr"})

    assert [p["platform_id"] for p in postings] == ["600922", "598975"]
    assert drain_non_local("taleez") == 1


def test_scrape_without_entries_is_empty():
    assert taleez.scrape({}) == []
    assert taleez.probe({}) is None


# --- probe ---

@responses.activate
def test_probe_reads_the_list_only():
    responses.add(responses.GET, _LIST, body=_fx("donecle_careez.json"))

    drain_errors()
    result = taleez.probe({"taleez_companies": ["donecle"]})

    assert result["structure_ok"] is True and len(result["postings"]) == 3
    assert len(responses.calls) == 1
    assert drain_errors() == {}


@responses.activate
def test_probe_of_a_list_without_its_jobs_block_has_no_structure():
    data = json.loads(_fx("donecle_careez.json"))
    del data["jobs"]
    responses.add(responses.GET, _LIST, body=json.dumps(data))

    result = taleez.probe({"taleez_companies": ["donecle"]})

    assert result["structure_ok"] is False and result["reason"]


@responses.activate
def test_probe_connection_error_is_unreachable():
    responses.add(responses.GET, _LIST, body=requests.ConnectionError("down"))

    result = taleez.probe({"taleez_companies": ["donecle"]})

    assert result.get("unreachable") and result["structure_ok"] is False


@responses.activate
@pytest.mark.parametrize("status", [401, 403])
def test_probe_401_and_403_are_a_wall(status):
    responses.add(responses.GET, _LIST, status=status)

    assert taleez.probe({"taleez_companies": ["donecle"]}).get("wall")
