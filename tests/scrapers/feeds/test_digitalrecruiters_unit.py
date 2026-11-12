"""Unit tests for Digitalrecruiters (issue #561): tenants, sitemap, ad page, detection. All pure."""

import pytest

from door.scrapers.feeds import digitalrecruiters as dr
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "digitalrecruiters"


def _read(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("entry, host", [
    ("recrutement.monoprix.fr", "recrutement.monoprix.fr"),
    ("https://recrutement.monoprix.fr/fr/annonces", "recrutement.monoprix.fr"),
    ("  Recrutement.Monoprix.FR/ ", "recrutement.monoprix.fr"),
    ("http://recrutement.afflelou.com:443/fr", "recrutement.afflelou.com"),
])
def test_the_tenant_is_the_host_of_an_entry(entry, host):
    assert dr._host(entry) == host
    assert dr._base(entry) == f"https://{host}"


def test_the_sitemap_lists_the_ads_with_their_numbers():
    children, items = dr.parse_sitemap(_read("monoprix_sitemap.xml"))

    assert children == []
    assert [i["id"] for i in items] == ["4672793", "4672737", "4672729", "4672627"]
    first = items[0]
    assert first["url"] == "https://recrutement.monoprix.fr/fr/annonce/4672793-employe-de-rayon-maison-loisirs-fh-75014-paris"
    assert first["title"] == "employe de rayon maison loisirs fh 75014 paris"
    assert first["lastmod"].startswith("2026-10-31T16:03:16")


def test_a_sitemap_index_names_its_children_and_a_page_in_it_that_is_no_ad_is_skipped():
    xml = ('<sitemapindex><sitemap><loc>https://t.example/sitemap-1.xml</loc></sitemap></sitemapindex>')
    assert dr.parse_sitemap(xml) == (["https://t.example/sitemap-1.xml"], [])
    urlset = ('<urlset><url><loc>https://t.example/fr/annonces</loc></url>'
              '<url><loc>https://t.example/fr/annonce/12-a-b</loc></url>'
              '<url><loc>https://t.example/fr/annonce/12-a-b</loc></url></urlset>')
    assert [i["id"] for i in dr.parse_sitemap(urlset)[1]] == ["12"]


@pytest.mark.parametrize("text", ["<html><body>Maintenance</body></html>", "", "not xml at all <"])
def test_a_page_that_is_no_sitemap_raises(text):
    with pytest.raises(ValueError):
        dr.parse_sitemap(text)


def test_an_ad_page_gives_its_json_ld():
    ad = dr.parse_ad(_read("monoprix_4672793.html"))

    assert ad["title"] == "Employé de rayon maison - loisirs F/H"
    assert ad["company"] == "Groupe MONOPRIX"
    assert ad["location"] == "Paris"
    assert ad["posted_at"] == "2026-10-31"
    assert ad["description"].startswith("Vous aimez conseiller et surprendre ?")
    assert "<" not in ad["description"] and "&nbsp;" not in ad["description"]


def test_an_ad_without_a_place_or_with_a_list_of_places():
    assert dr.parse_ad('<script type="application/ld+json">{"@type":"JobPosting","title":"A","hiringOrganization":{"name":"X"}}</script>')["location"] == ""
    two = ('<script type="application/ld+json">{"@type":"JobPosting","title":"A","jobLocation":['
           '{"address":{"addressLocality":"Lyon"}},{"address":{"addressLocality":"Lille"}},{"address":{"addressLocality":"Lyon"}}]}</script>')
    assert dr.parse_ad(two)["location"] == "Lyon; Lille"


def test_a_page_without_a_job_posting_is_no_ad():
    assert dr.parse_ad("<html><body>Page introuvable</body></html>") is None
    assert dr.parse_ad('<script type="application/ld+json">{"@type":"Organization"}</script>') is None
    assert dr.parse_ad('<script type="application/ld+json">{broken</script>') is None


def test_the_posting_carries_the_tenant_in_its_id():
    from datetime import datetime, timezone

    item = dr.parse_sitemap(_read("monoprix_sitemap.xml"))[1][0]
    ad = dr.parse_ad(_read("monoprix_4672793.html"))
    posting = dr._to_posting(item, ad, "recrutement.monoprix.fr", "", datetime(2026, 11, 1, tzinfo=timezone.utc))

    assert posting["id"] == "digitalrecruiters.recrutement-monoprix-fr-4672793"
    assert posting["platform_id"] == "recrutement.monoprix.fr-4672793"
    assert posting["company"] == "Groupe MONOPRIX" and posting["location"] == "Paris"
    assert posting["url"] == item["url"] and posting["apply_url"] == item["url"]
    assert posting["posted_at"].startswith("2026-10-31")
    assert posting["source"] == "digitalrecruiters"
    named = dr._to_posting(item, ad, "recrutement.monoprix.fr", "Monoprix", datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert named["company"] == "Monoprix"


def test_ads_on_topic_by_their_slug_are_read_first_and_the_newest_first_within_a_tier():
    items = [
        {"id": "1", "title": "responsable de magasin", "lastmod": "2026-10-31T10:00:00+00:00"},
        {"id": "2", "title": "employe de caisse", "lastmod": "2026-10-29T10:00:00+00:00"},
        {"id": "3", "title": "hotesse de caisse", "lastmod": "2026-10-30T10:00:00+00:00"},
        {"id": "4", "title": "boucher", "lastmod": "2026-10-28T10:00:00+00:00"},
    ]

    ranked = dr._rank(items, {"search_keywords": ["caisse"]})

    assert [i["id"] for i in ranked] == ["3", "2", "1", "4"]
    assert [i["id"] for i in dr._rank(items, {})] == ["1", "3", "2", "4"]


# --- detection ---

@pytest.mark.parametrize("url, entry", [
    ("https://acme.digitalrecruiters.com/fr/annonces", "acme.digitalrecruiters.com"),
    ("https://carrieres-acme.digitalrecruiters.com/", "carrieres-acme.digitalrecruiters.com"),
    ("https://app.digitalrecruiters.com/connexion", None),
    ("https://api.digitalrecruiters.com/careers/v1/x", None),
    ("https://www.digitalrecruiters.com/", None),
    ("https://digitalrecruiters.com/", None),
    ("https://recrutement.monoprix.fr/fr/annonces", None),
])
def test_a_link_on_the_platforms_own_wildcard_host_names_a_tenant(url, entry):
    det = dr.detect_url(url)
    assert (det.entry if det else None) == entry
    if det:
        assert det.platform == "digitalrecruiters"


def test_a_career_site_on_the_employers_own_domain_is_known_by_its_page():
    det = dr.detect_html(_read("monoprix_home.html"), "https://recrutement.monoprix.fr/fr")

    assert det.platform == "digitalrecruiters" and det.entry == "recrutement.monoprix.fr"
    assert "recrutement.monoprix.fr" in det.evidence


def test_the_tenant_falls_back_to_the_pages_host_and_other_pages_are_not_detected():
    page = _read("monoprix_home.html").replace('domain_name:"recrutement.monoprix.fr"', "")
    assert dr.detect_html(page, "https://recrutement.monoprix.fr/fr").entry == "recrutement.monoprix.fr"
    assert dr.detect_html("<html><body>Rejoignez-nous</body></html>", "https://example.fr/") is None
    assert dr.detect_html('<a href="https://www.digitalrecruiters.com/">Cegid</a>', "https://example.fr/") is None


def test_the_feed_is_confirmed_by_the_sitemap_not_a_json_list():
    assert dr.feed_url("recrutement.monoprix.fr") is None
    assert dr.alive_url("recrutement.monoprix.fr") == "https://recrutement.monoprix.fr/sitemap.xml"
    assert dr.name_probes("monoprix") == []
