"""Unit tests for the Beetween helpers: entries, the WordPress job list, the JSON-LD ad and the feed detection."""

import json
from datetime import datetime, timezone

import pytest

from door.scrapers.feeds import beetween
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "beetween"


def _fx(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


def _page(**fields) -> str:
    ad = {"@type": "JobPosting", "title": "Comptable", "description": "&lt;p&gt;Bonjour&lt;/p&gt;", **fields}
    return f'<html><head><script type="application/ld+json">{json.dumps(ad)}</script></head></html>'


# --- entries ---

@pytest.mark.parametrize("entry,base", [
    ("giboire", "https://giboire.nous-recrutons.fr"),
    (" Giboire ", "https://giboire.nous-recrutons.fr"),
    ("giboire.nous-recrutons.fr", "https://giboire.nous-recrutons.fr"),
    ("https://giboire.nous-recrutons.fr/poste/x/", "https://giboire.nous-recrutons.fr"),
    ("recrutement.clermontmetropole.eu", "https://recrutement.clermontmetropole.eu"),
    ("https://recrutement.clermontmetropole.eu/offres-emploi/", "https://recrutement.clermontmetropole.eu"),
])
def test_an_entry_is_a_slug_or_a_career_host(entry, base):
    assert beetween._base(entry) == base


def test_the_job_list_url_asks_for_fifty_and_only_the_fields_read():
    url = beetween._list_url("https://giboire.nous-recrutons.fr", 2)

    assert url.startswith("https://giboire.nous-recrutons.fr/wp-json/wp/v2/job?")
    assert "per_page=50" in url and "page=2" in url and "_fields=id,date,link,title" in url


# --- the job list ---

def test_the_job_list_gives_id_title_link_and_day():
    jobs = beetween.parse_list(_fx("giboire_jobs_p1.json"))

    assert [j["id"] for j in jobs] == ["2080", "2079"]
    assert jobs[0]["title"] == "Responsable Développement Bouches du Rhône & Var"
    assert jobs[0]["url"] == "https://giboire.nous-recrutons.fr/poste/0iwubmg1rl-responsable-developpement-bouches-du-rhone-var/"
    assert jobs[0]["posted_at"] == "2026-10-28T09:20:25"


def test_a_job_without_a_link_is_left_out():
    text = json.dumps([{"id": 1, "title": {"rendered": "A"}}, {"id": 2, "link": "https://x.fr/poste/a/", "title": {"rendered": "B"}}])

    assert [j["id"] for j in beetween.parse_list(text)] == ["2"]


@pytest.mark.parametrize("text", ["<html>not json</html>", '{"code": "rest_no_route"}', "", "null"])
def test_a_page_that_is_no_job_list_raises(text):
    with pytest.raises(ValueError):
        beetween.parse_list(text)


def test_an_empty_list_is_a_career_site_without_open_jobs():
    assert beetween.parse_list("[]") == []


# --- one ad page ---

def test_the_ad_gives_text_place_day_and_organisation():
    ad = beetween.parse_ad(_fx("giboire_ad_0alwstmu28.html"))

    assert ad["title"] == "Comptable de copropriété (F/H)"
    assert ad["organization"] == "Maestro Syndic"
    assert ad["posted_at"] == "2026-10-27"
    assert ad["location"] == "Rennes, France"
    assert "Recouvrement des charges" in ad["description"]
    assert "Titulaire d’un BAC +2" in ad["description"] and "c'était vous" in ad["description"]
    assert "<" not in ad["description"] and "&" not in ad["description"]


def test_a_page_without_a_job_posting_is_no_ad():
    assert beetween.parse_ad("<html><body>404</body></html>") is None
    assert beetween.parse_ad('<script type="application/ld+json">{"@type": "Organization"}</script>') is None
    assert beetween.parse_ad('<script type="application/ld+json">{broken</script>') is None


@pytest.mark.parametrize("place,text", [
    ({"address": {"addressLocality": "Lyon", "addressRegion": "France"}}, "Lyon, France"),
    ({"address": {"addressLocality": "Lyon"}}, "Lyon"),
    ({"address": {"addressLocality": "Lyon", "addressRegion": "Lyon"}}, "Lyon"),
    ([{"address": {"addressLocality": "Lyon"}}, {"address": {"addressLocality": "Nantes"}}, {"address": {"addressLocality": "Lyon"}}], "Lyon; Nantes"),
    ({"address": {}}, ""),
    (None, ""),
])
def test_the_location_text(place, text):
    assert beetween.parse_ad(_page(jobLocation=place))["location"] == text


def test_the_description_is_the_missions_then_the_profile():
    ad = beetween.parse_ad(_page(description="&lt;p&gt;Missions&lt;/p&gt;", qualifications="&lt;p&gt;Profil&lt;/p&gt;"))

    assert ad["description"].split() == ["Missions", "Profil"]


# --- mapping ---

def test_a_posting_folds_the_host_into_the_id_and_the_followed_name_wins():
    job = beetween.parse_list(_fx("giboire_jobs_p1.json"))[1]
    ad = beetween.parse_ad(_fx("giboire_ad_0alwstmu28.html"))
    now = datetime(2026, 11, 1, tzinfo=timezone.utc)

    posting = beetween._to_posting(job, ad, "https://giboire.nous-recrutons.fr", "Giboire", now)

    assert posting["platform_id"] == "giboire.nous-recrutons.fr-2079"
    assert posting["id"] == "beetween.giboire-nous-recrutons-fr-2079"
    assert posting["company"] == "Giboire" and posting["source"] == "beetween"
    assert posting["apply_url"] == posting["url"] == job["url"]
    assert posting["posted_at"].startswith("2026-10-27")


def test_without_a_followed_name_the_ads_organisation_names_the_company():
    job = beetween.parse_list(_fx("giboire_jobs_p1.json"))[1]
    ad = beetween.parse_ad(_fx("giboire_ad_0alwstmu28.html"))

    posting = beetween._to_posting(job, ad, "https://giboire.nous-recrutons.fr", "", datetime.now(timezone.utc))

    assert posting["company"] == "Maestro Syndic"


def test_a_posting_without_its_ad_page_has_the_list_day_and_no_text():
    job = beetween.parse_list(_fx("giboire_jobs_p1.json"))[0]

    posting = beetween._to_posting(job, None, "https://giboire.nous-recrutons.fr", "", datetime.now(timezone.utc))

    assert posting["description"] == "" and posting["posted_at"].startswith("2026-10-28")
    assert posting["company"] == "giboire.nous-recrutons.fr"


# --- feed detection ---

@pytest.mark.parametrize("url,entry", [
    ("https://giboire.nous-recrutons.fr/", "giboire"),
    ("https://giboire.nous-recrutons.fr/poste/0iwubmg1rl-responsable/", "giboire"),
    ("GIBOIRE.nous-recrutons.fr/offres-emploi/", "giboire"),
    ("https://www.nous-recrutons.fr/", None),
    ("https://nous-recrutons.fr/", None),
    ("https://a.b.nous-recrutons.fr/", None),
    ("https://example.invalid/x", None),
])
def test_detect_url_names_the_tenant_of_a_career_host(url, entry):
    det = beetween.detect_url(url)

    assert (det.entry if det else None) == entry
    assert (det is None) or det.platform == "beetween"


def test_a_cname_to_a_tenant_names_it():
    det = beetween.detect_cname("recrutement.clermontmetropole.eu", "clermont.nous-recrutons.fr", "CNAME of x")

    assert det.platform == "beetween" and det.entry == "clermont"
    assert beetween.detect_cname("x.fr", "www.nous-recrutons.fr", "w") is None
    assert beetween.detect_cname("x.fr", "other.example.com", "w") is None


_OWN_DOMAIN = ('<link rel="stylesheet" href="https://recrutement.clermontmetropole.eu/wp-content/themes/x/style.css">'
               '<a href="https://recrutement.clermontmetropole.eu/poste/tcd9cr0cgv-chef-de-projet-investissements/">Voir</a>')


def test_an_own_domain_career_site_is_known_by_its_wordpress_job_links():
    det = beetween.detect_html(_OWN_DOMAIN, "https://recrutement.clermontmetropole.eu/")

    assert det.platform == "beetween" and det.entry == "recrutement.clermontmetropole.eu"


@pytest.mark.parametrize("html", [
    "<p>nothing</p>",
    '<a href="https://acme.fr/poste/chef-de-projet/">x</a> wp-content',  # no Beetween-style job key
    '<a href="https://acme.fr/poste/tcd9cr0cgv-chef-de-projet/">x</a>',  # not WordPress
])
def test_other_pages_are_not_detected(html):
    assert beetween.detect_html(html, "https://acme.fr/") is None


def test_the_feed_has_no_json_check_and_no_name_probe():
    assert beetween.feed_url("giboire") is None
    assert beetween.name_probes("giboire") == []
