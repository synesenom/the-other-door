"""Fixture tests for Digitalrecruiters (issue #561): Monoprix's and Franprix's career sites, trimmed and rewritten."""

import pytest
import requests
import responses

from door.core.models import JobPosting
from door.scrapers import drain_errors, drain_non_local, drain_pushback
from door.scrapers.feeds import digitalrecruiters as dr
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "digitalrecruiters"
_MONO = "https://recrutement.monoprix.fr"
_FRAN = "https://recrutement.franprix.fr"
_ADS = {
    "4672793": "employe-de-rayon-maison-loisirs-fh-75014-paris",
    "4672737": "employe-de-caisse-accueil-fh-68000-colmar",
    "4672729": "employe-de-rayon-epicerie-entretien-fh-68000-colmar",
    "4672627": "employee-employe-de-rayon-charcuterie-libre-service-75015-paris",
}


def _read(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


def _ad_url(base: str, ad_id: str, slug: str) -> str:
    return f"{base}/fr/annonce/{ad_id}-{slug}"


def _serve_monoprix(gone=("4672627",)):
    responses.add(responses.GET, f"{_MONO}/sitemap.xml", body=_read("monoprix_sitemap.xml"), content_type="application/xml")
    for ad_id, slug in _ADS.items():
        if ad_id in gone:
            responses.add(responses.GET, _ad_url(_MONO, ad_id, slug), status=404)
        else:
            responses.add(responses.GET, _ad_url(_MONO, ad_id, slug), body=_read(f"monoprix_{ad_id}.html"))


def _serve_franprix():
    responses.add(responses.GET, f"{_FRAN}/sitemap.xml", body=_read("franprix_sitemap.xml"))
    responses.add(responses.GET, _ad_url(_FRAN, "4663815", "analyste-pricing-stage-fh-92400-courbevoie"),
                  body=_read("franprix_4663815.html"))
    responses.add(responses.GET, _ad_url(_FRAN, "4660541", "chef-de-rayon-fh-94320-thiais"),
                  body=_read("franprix_4660541.html"))


def _ad_calls():
    return [c.request.url for c in responses.calls if "/annonce/" in c.request.url]


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


@responses.activate
def test_scrape_reads_the_sitemap_then_each_ad_for_its_text_and_place():
    _serve_monoprix()
    drain_errors()

    postings = dr.scrape({"digitalrecruiters_sites": ["recrutement.monoprix.fr"]})

    assert len(postings) == 3
    for p in postings:
        JobPosting.model_validate(p)
        assert p["source"] == "digitalrecruiters" and p["company"] == "Groupe MONOPRIX"
        assert p["description"] and "<" not in p["description"]
        assert p["apply_url"] == p["url"] and p["url"].startswith(f"{_MONO}/fr/annonce/")
    by_title = {p["title"]: p for p in postings}
    assert by_title["Employé de caisse accueil F/H"]["location"] == "Colmar"
    assert by_title["Employé de rayon maison - loisirs F/H"]["location"] == "Paris"
    assert by_title["Employé de rayon maison - loisirs F/H"]["posted_at"].startswith("2026-10-31")
    assert len({p["id"] for p in postings}) == 3
    # a closed ad (404) between the sitemap and the page is no error
    assert drain_errors() == {}


@responses.activate
def test_known_ads_cost_no_detail_request():
    _serve_monoprix()
    known = frozenset({"recrutement.monoprix.fr-4672793", "recrutement.monoprix.fr-4672737"})

    postings = dr.scrape({"digitalrecruiters_sites": ["recrutement.monoprix.fr"]}, known)

    assert [p["title"] for p in postings] == ["Employé de rayon épicerie - entretien F/H"]
    assert [u.rsplit("/", 1)[1].split("-")[0] for u in _ad_calls()] == ["4672729", "4672627"]


@responses.activate
def test_the_ads_on_topic_are_read_first_and_the_cap_cuts_the_rest(monkeypatch):
    _serve_monoprix()
    monkeypatch.setattr(dr, "_MAX_PAGES", 2)

    postings = dr.scrape({"digitalrecruiters_sites": ["recrutement.monoprix.fr"], "search_keywords": ["caisse"]})

    assert [p["title"] for p in postings] == ["Employé de caisse accueil F/H", "Employé de rayon épicerie - entretien F/H"]
    assert len(_ad_calls()) == 2


@responses.activate
def test_the_followed_name_wins_and_a_url_entry_works():
    _serve_monoprix()

    postings = dr.scrape({"digitalrecruiters_sites": [f"{_MONO}/fr/annonces"],
                          "_names": {"digitalrecruiters_sites": {"recrutement.monoprix.fr/fr/annonces": "Monoprix"}}})

    assert {p["company"] for p in postings} == {"Monoprix"}


@responses.activate
def test_two_tenants_are_two_sites():
    _serve_monoprix()
    _serve_franprix()

    postings = dr.scrape({"digitalrecruiters_sites": ["recrutement.monoprix.fr", "recrutement.franprix.fr",
                                                      "recrutement.monoprix.fr"]})

    assert len(postings) == 5
    assert {p["company"] for p in postings} == {"Groupe MONOPRIX", "Franprix"}
    assert len({p["id"] for p in postings}) == 5
    stage = next(p for p in postings if p["title"].startswith("Analyste pricing"))
    assert stage["location"] == "Courbevoie" and "Power BI" in stage["description"]


@responses.activate
def test_a_failing_ad_is_recorded_and_the_others_still_come():
    _serve_monoprix(gone=())
    responses.replace(responses.GET, _ad_url(_MONO, "4672737", _ADS["4672737"]), status=500)
    drain_errors()

    postings = dr.scrape({"digitalrecruiters_sites": ["recrutement.monoprix.fr"]})

    assert len(postings) == 3
    assert any("4672737" in e for e in drain_errors()["digitalrecruiters"])


@responses.activate
def test_an_ad_page_without_json_ld_is_recorded():
    _serve_monoprix(gone=())
    responses.replace(responses.GET, _ad_url(_MONO, "4672627", _ADS["4672627"]), body="<html><body>Oups</body></html>")
    drain_errors()

    assert len(dr.scrape({"digitalrecruiters_sites": ["recrutement.monoprix.fr"]})) == 3
    assert any("4672627" in e for e in drain_errors()["digitalrecruiters"])


@responses.activate
def test_a_failed_sitemap_is_a_recorded_error_not_a_raise():
    responses.add(responses.GET, f"{_MONO}/sitemap.xml", status=500)
    drain_errors()

    assert dr.scrape({"digitalrecruiters_sites": ["recrutement.monoprix.fr"]}) == []
    assert drain_errors()["digitalrecruiters"]


@responses.activate
@pytest.mark.parametrize("status", [429, 403])
def test_a_refusal_is_pushback_and_ends_the_site(status):
    _serve_monoprix(gone=())
    responses.replace(responses.GET, _ad_url(_MONO, "4672737", _ADS["4672737"]), status=status)
    drain_pushback("digitalrecruiters")
    drain_errors()

    postings = dr.scrape({"digitalrecruiters_sites": ["recrutement.monoprix.fr"]})

    # newest first: the two ads before the refused one are kept, the last is left for the next run
    assert [p["platform_id"].rsplit("-", 1)[1] for p in postings] == ["4672729", "4672793"]
    assert not any(c.request.url.endswith("charcuterie-libre-service-75015-paris") for c in responses.calls)
    assert drain_pushback("digitalrecruiters") is True
    assert drain_errors()["digitalrecruiters"]


@responses.activate
def test_a_refused_sitemap_is_pushback():
    responses.add(responses.GET, f"{_MONO}/sitemap.xml", status=403)
    drain_pushback("digitalrecruiters")

    assert dr.scrape({"digitalrecruiters_sites": ["recrutement.monoprix.fr"]}) == []
    assert drain_pushback("digitalrecruiters") is True


@responses.activate
def test_a_page_that_is_not_a_sitemap_is_a_recorded_error():
    responses.add(responses.GET, f"{_MONO}/sitemap.xml", body="<html><body>Maintenance</body></html>")
    drain_errors()

    assert dr.scrape({"digitalrecruiters_sites": ["recrutement.monoprix.fr"]}) == []
    assert drain_errors()["digitalrecruiters"]


@responses.activate
def test_a_sitemap_index_is_followed():
    responses.add(responses.GET, f"{_MONO}/sitemap.xml", body=(
        f"<sitemapindex><sitemap><loc>{_MONO}/sitemap-1.xml</loc></sitemap></sitemapindex>"))
    responses.add(responses.GET, f"{_MONO}/sitemap-1.xml", body=_read("monoprix_sitemap.xml"))
    for ad_id, slug in _ADS.items():
        if ad_id != "4672627":
            responses.add(responses.GET, _ad_url(_MONO, ad_id, slug), body=_read(f"monoprix_{ad_id}.html"))
    responses.add(responses.GET, _ad_url(_MONO, "4672627", _ADS["4672627"]), status=404)

    assert len(dr.scrape({"digitalrecruiters_sites": ["recrutement.monoprix.fr"]})) == 3


@responses.activate
def test_scrape_drops_ads_in_another_country():
    _serve_monoprix()
    responses.replace(responses.GET, _ad_url(_MONO, "4672737", _ADS["4672737"]),
                      body=_read("monoprix_4672737.html").replace('"addressLocality":"Colmar"', '"addressLocality":"Vienna, Austria"'))
    drain_non_local("digitalrecruiters")

    postings = dr.scrape({"digitalrecruiters_sites": ["recrutement.monoprix.fr"], "location": "Paris, France"})

    assert len(postings) == 2
    assert drain_non_local("digitalrecruiters") == 1


def test_no_sites_no_request():
    assert dr.scrape({}) == []
    assert dr.probe({}) is None


@responses.activate
def test_probe_reads_the_first_sitemap_with_one_request():
    responses.add(responses.GET, f"{_MONO}/sitemap.xml", body=_read("monoprix_sitemap.xml"))
    drain_errors()

    result = dr.probe({"digitalrecruiters_sites": ["recrutement.monoprix.fr", "recrutement.franprix.fr"]})

    assert result["structure_ok"] is True and len(result["postings"]) == 4
    assert len(responses.calls) == 1
    assert drain_errors() == {}


@responses.activate
def test_probe_drift_without_a_sitemap():
    responses.add(responses.GET, f"{_MONO}/sitemap.xml", body=_read("monoprix_sitemap.xml").replace("urlset", "list"))

    result = dr.probe({"digitalrecruiters_sites": ["recrutement.monoprix.fr"]})

    assert result["structure_ok"] is False and result["reason"]


@responses.activate
def test_probe_unreachable_and_wall():
    responses.add(responses.GET, f"{_MONO}/sitemap.xml", body=requests.ConnectionError("down"))
    down = dr.probe({"digitalrecruiters_sites": ["recrutement.monoprix.fr"]})
    assert down["structure_ok"] is False and down.get("unreachable") is True
    responses.replace(responses.GET, f"{_MONO}/sitemap.xml", status=403)
    walled = dr.probe({"digitalrecruiters_sites": ["recrutement.monoprix.fr"]})
    assert walled["structure_ok"] is False and walled.get("wall") is True
