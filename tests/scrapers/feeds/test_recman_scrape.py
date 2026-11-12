"""Fixture tests for Recman: Professionals Nord's live sitemap and ads (tenant ``pn``), trimmed and their text rewritten."""

import pytest
import requests
import responses

from door.core.models import JobPosting
from door.scrapers import drain_errors, drain_non_local, drain_pushback
from door.scrapers.feeds import recman
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "recman"
_MAP = "https://pn.recman.page/sitemap.xml"
_IDS = ["490875", "477333", "429148"]


def _fx(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


def _job(jid: str) -> str:
    return f"https://pn.recman.page/job/{jid}"


def _mock_all():
    responses.add(responses.GET, _MAP, body=_fx("pn_sitemap.xml"))
    for jid in _IDS:
        responses.add(responses.GET, _job(jid), body=_fx(f"pn_{jid}.html"))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


@responses.activate
def test_scrape_maps_every_listed_job():
    _mock_all()

    postings = recman.scrape({"recman_companies": ["pn"]})

    assert [p["platform_id"] for p in postings] == _IDS
    by_id = {p["platform_id"]: p for p in postings}
    first = by_id["429148"]
    JobPosting.model_validate(first)
    assert first["id"] == "recman.429148"
    assert first["title"] == "Elektronikingenjör till ShortLink!"
    assert first["company"] == "Professionals Nord Rekrytering AB"
    assert first["location"] == "Linköping, SE"
    assert first["url"] == _job("429148") and first["apply_url"] == first["url"]
    assert first["posted_at"].startswith("2025-04-29")
    assert "FPGA" in first["description"] and "<" not in first["description"]
    assert first["source"] == "recman"
    assert by_id["490875"]["location"] == ""
    assert len(responses.calls) == 4


@responses.activate
def test_known_ids_skip_the_detail_requests():
    responses.add(responses.GET, _MAP, body=_fx("pn_sitemap.xml"))
    responses.add(responses.GET, _job("429148"), body=_fx("pn_429148.html"))

    postings = recman.scrape({"recman_companies": ["pn"]}, known_ids=frozenset({"490875", "477333"}))

    assert [p["platform_id"] for p in postings] == ["429148"]
    assert len(responses.calls) == 2


@responses.activate
def test_the_followed_name_wins():
    _mock_all()

    postings = recman.scrape({"recman_companies": ["pn"], "_names": {"recman_companies": {"pn": "Professionals Nord"}}})

    assert {p["company"] for p in postings} == {"Professionals Nord"}


@responses.activate
def test_an_entry_on_the_employers_own_host_is_read_there():
    responses.add(responses.GET, "https://stillinger.signo.no/sitemap.xml",
                  body=_fx("pn_sitemap.xml").replace("pn.recman.page", "stillinger.signo.no"))
    for jid in _IDS:
        responses.add(responses.GET, f"https://stillinger.signo.no/job/{jid}", body=_fx(f"pn_{jid}.html"))

    postings = recman.scrape({"recman_companies": ["stillinger.signo.no"]})

    assert len(postings) == 3 and postings[0]["url"].startswith("https://stillinger.signo.no/job/")


@responses.activate
def test_the_same_job_listed_by_two_entries_comes_once():
    _mock_all()
    responses.add(responses.GET, "https://pn.recman.io/sitemap.xml", body=_fx("pn_sitemap.xml"))

    postings = recman.scrape({"recman_companies": ["pn", "pn.recman.io"]})

    assert [p["platform_id"] for p in postings] == _IDS


@responses.activate
def test_a_failing_sitemap_is_a_recorded_error():
    responses.add(responses.GET, "https://bad.recman.page/sitemap.xml", status=500)
    _mock_all()

    drain_errors()
    assert len(recman.scrape({"recman_companies": ["bad", "pn"]})) == 3
    assert "bad" in drain_errors()["recman"][0]


@responses.activate
def test_a_tenant_that_does_not_exist_is_a_recorded_error_not_an_empty_board():
    responses.add(responses.GET, "https://gone.recman.page/sitemap.xml", body=_fx("unknown.html"))

    drain_errors()
    assert recman.scrape({"recman_companies": ["gone"]}) == []
    assert "gone" in drain_errors()["recman"][0]


@responses.activate
def test_a_failing_ad_is_recorded_and_the_others_kept():
    responses.add(responses.GET, _MAP, body=_fx("pn_sitemap.xml"))
    responses.add(responses.GET, _job("490875"), status=500)
    responses.add(responses.GET, _job("477333"), body=_fx("pn_477333.html"))
    responses.add(responses.GET, _job("429148"), body="<html>no ad</html>")

    drain_errors()
    postings = recman.scrape({"recman_companies": ["pn"]})

    assert [p["platform_id"] for p in postings] == ["477333"]
    assert len(drain_errors()["recman"]) == 2


@responses.activate
@pytest.mark.parametrize("status", [429, 403])
def test_pushback_is_recorded_and_stops_the_board(status):
    responses.add(responses.GET, _MAP, status=status)

    drain_errors()
    drain_pushback("recman")
    assert recman.scrape({"recman_companies": ["pn"]}) == []

    assert drain_pushback("recman") is True
    assert drain_errors()["recman"]


@responses.activate
def test_pushback_on_an_ad_stops_the_rest_of_the_board():
    responses.add(responses.GET, _MAP, body=_fx("pn_sitemap.xml"))
    responses.add(responses.GET, _job("490875"), status=429)

    drain_pushback("recman")
    recman.scrape({"recman_companies": ["pn"]})

    assert drain_pushback("recman") is True
    assert [c.request.url for c in responses.calls].count(_job("429148")) == 0


@responses.activate
def test_a_posting_in_another_country_is_dropped():
    responses.add(responses.GET, _MAP, body=_fx("pn_sitemap.xml"))
    for jid in _IDS:
        body = _fx(f"pn_{jid}.html")
        if jid == "429148":
            body = body.replace('"addressCountry": "SE"', '"addressCountry": "DE"').replace("Linköping\", ", "Berlin\", ")
        responses.add(responses.GET, _job(jid), body=body)

    drain_non_local("recman")
    postings = recman.scrape({"recman_companies": ["pn"], "location": "Stockholm", "_country": "se"})

    assert "429148" not in {p["platform_id"] for p in postings}
    assert drain_non_local("recman") == 1


def test_scrape_without_entries_is_empty():
    assert recman.scrape({}) == []
    assert recman.probe({}) is None


# --- probe ---

@responses.activate
def test_probe_reads_the_sitemap_only():
    responses.add(responses.GET, _MAP, body=_fx("pn_sitemap.xml"))

    drain_errors()
    result = recman.probe({"recman_companies": ["pn"]})

    assert result["structure_ok"] is True and len(result["postings"]) == 3
    assert len(responses.calls) == 1
    assert drain_errors() == {}


@responses.activate
def test_probe_of_a_tenant_without_open_jobs_is_still_a_sitemap():
    responses.add(responses.GET, _MAP, body=_fx("pn_sitemap.xml").split("<url>\n<loc>https://pn.recman.page/job/")[0] + "</urlset>\n")

    result = recman.probe({"recman_companies": ["pn"]})

    assert result["structure_ok"] is True and result["postings"] == []


@responses.activate
def test_probe_of_the_page_a_dead_tenant_serves_has_no_structure():
    responses.add(responses.GET, _MAP, body=_fx("unknown.html"))

    result = recman.probe({"recman_companies": ["pn"]})

    assert result["structure_ok"] is False and result["reason"]


@responses.activate
def test_probe_connection_error_is_unreachable():
    responses.add(responses.GET, _MAP, body=requests.ConnectionError("down"))

    result = recman.probe({"recman_companies": ["pn"]})

    assert result.get("unreachable") and result["structure_ok"] is False


@responses.activate
def test_probe_403_is_a_wall():
    responses.add(responses.GET, _MAP, status=403)

    assert recman.probe({"recman_companies": ["pn"]}).get("wall")
