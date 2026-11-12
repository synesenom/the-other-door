"""Unit tests for Talentsoft's pure helpers (issue #559): AGRICA's list page, RSS feed and ad page, trimmed."""

from datetime import datetime, timezone

import pytest

from door.scrapers.feeds import talentsoft
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "talentsoft"


def _read(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("entry, base", [
    ("agrica-career.talent-soft.com", "https://agrica-career.talent-soft.com"),
    ("https://agrica-career.talent-soft.com/offre-de-emploi/liste-offres.aspx", "https://agrica-career.talent-soft.com"),
    ("Recrutement.Exemple.fr:443/", "https://recrutement.exemple.fr"),
])
def test_base_is_the_host_of_an_entry_or_a_link(entry, base):
    assert talentsoft._base(entry) == base


@pytest.mark.parametrize("url, platform_id", [
    ("/offre-de-emploi/emploi-analyste-data-h-f_2286.aspx", "2286"),
    ("https://x.talent-soft.com/Pages/Offre/detailoffre.aspx?idOffre=2287&idOrigine=502&LCID=1036", "2287"),
    ("/offre-de-emploi/liste-offres.aspx", ""),
])
def test_ad_id_reads_both_link_shapes(url, platform_id):
    assert talentsoft._ad_id(url) == platform_id


def test_parse_list_reads_the_total_the_employer_and_every_card():
    total, name, cards = talentsoft.parse_list(_read("agrica_list_1.html"))

    assert total == 5 and name == "AGRICA"
    assert [c["id"] for c in cards] == ["2287", "2286", "2281"]
    first = cards[0]
    assert first["title"] == "COMPTABLE TECHNIQUE ASSURANCE H/F"
    assert first["url"] == "/offre-de-emploi/emploi-comptable-technique-assurance-h-f_2287.aspx"
    assert first["ref"] == "2026-218-2287"
    assert first["posted_at"] == datetime(2026, 10, 31, tzinfo=timezone.utc)
    assert first["location"] == "Paris (75)"


def test_parse_list_of_a_page_without_cards_is_empty():
    assert talentsoft.parse_list("<html><title>Maintenance</title></html>") == (None, "", [])


def test_parse_feed_maps_each_item_by_its_offer_id():
    ads = talentsoft.parse_feed(_read("agrica_rss.xml"))

    assert list(ads) == ["2287", "2286", "2281", "2270"]
    ad = ads["2287"]
    assert ad["title"] == "COMPTABLE TECHNIQUE ASSURANCE H/F"
    assert ad["ref"] == "2026-218-2287"
    assert ad["location"] == "Paris" and ad["contract"] == "CDI"
    assert ad["posted_at"] == datetime(2026, 10, 30, 23, 30, 14, tzinfo=timezone.utc)
    assert ad["description"].startswith("Description du poste") and "<" not in ad["description"]
    assert "rapprochements bancaires" in ad["description"]


def test_parse_feed_rejects_what_is_not_rss():
    with pytest.raises(ValueError):
        talentsoft.parse_feed("<html><body>Maintenance</body></html>")


def test_parse_detail_reads_the_description_and_the_place():
    ad = talentsoft.parse_detail(_read("agrica_ad_2269.html"))

    assert ad["title"] == "ASSISTANT BUSINESS ANALYST STAGE H/F"
    assert ad["description"].startswith("Description du poste")
    assert "user stories" in ad["description"] and "Informations générales" not in ad["description"]
    assert "<" not in ad["description"]
    assert ad["location"] == "Paris 08"


def test_parse_detail_of_a_page_without_an_ad_is_none():
    assert talentsoft.parse_detail("<html><body>Page introuvable</body></html>") is None


# --- detection ---

@pytest.mark.parametrize("url, entry", [
    ("https://agrica-career.talent-soft.com/offre-de-emploi/liste-offres.aspx", "agrica-career.talent-soft.com"),
    ("https://acme-recrute.talent-soft.com/Pages/Offre/detailoffre.aspx?idOffre=3", "acme-recrute.talent-soft.com"),
    ("https://emploi.example.gov.pf/offre-de-emploi/emploi-chef-de-projet_12.aspx", "emploi.example.gov.pf"),
    ("https://emploi.example.gov.pf/handlers/offerRss.ashx?LCID=1036", "emploi.example.gov.pf"),
    ("https://emploi.example.gov.pf/Pages/Offre/detailoffre.aspx?idOffre=12", "emploi.example.gov.pf"),
])
def test_detect_url_names_the_host(url, entry):
    det = talentsoft.detect_url(url)
    assert det is not None and (det.platform, det.entry) == ("talentsoft", entry)


@pytest.mark.parametrize("url", [
    "https://www.talent-soft.com/", "https://talent-soft.com/fr/", "https://example.com/offre-de-emploi/",
    "https://example.com/careers/12",
])
def test_detect_url_ignores_the_vendor_and_other_sites(url):
    assert talentsoft.detect_url(url) is None


def test_detect_html_finds_a_career_site_on_the_employers_own_host():
    html = '<a href="/offre-de-emploi/liste-offres.aspx">Nos offres</a>'
    det = talentsoft.detect_html(html, "https://recrutement.example.fr/")
    assert (det.platform, det.entry) == ("talentsoft", "recrutement.example.fr")
    rss = '<link rel="alternate" type="application/rss+xml" href="/handlers/offerRss.ashx?LCID=1036">'
    assert talentsoft.detect_html(rss, "https://emploi.example.fr/").entry == "emploi.example.fr"
    assert talentsoft.detect_html("<p>Nos offres</p>", "https://example.fr/") is None


def test_detect_cname_follows_a_career_host_to_its_tenant():
    det = talentsoft.detect_cname("emploi.example.fr", "acme-career.talent-soft.com", "why")
    assert det.entry == "acme-career.talent-soft.com"
    assert talentsoft.detect_cname("emploi.example.fr", "elsewhere.example.com", "why") is None


def test_feed_url_is_none_and_alive_url_is_the_list_page():
    assert talentsoft.feed_url("x.talent-soft.com") is None
    assert talentsoft.alive_url("x.talent-soft.com") == "https://x.talent-soft.com/offre-de-emploi/liste-offres.aspx"
