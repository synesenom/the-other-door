"""Unit tests for the Taleez helpers: entries, the job list, the ad's JSON-LD and the feed detection."""

import json
from datetime import datetime, timezone

import pytest

from door.core import ats_detect
from door.scrapers.feeds import taleez
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "taleez"


def _fx(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


def _list() -> dict:
    return json.loads(_fx("donecle_careez.json"))


# --- entries ---

@pytest.mark.parametrize("entry,slug", [
    ("donecle", "donecle"),
    (" Donecle ", "donecle"),
    ("donecle.taleez.com", "donecle"),
    ("https://donecle.taleez.com/en", "donecle"),
    ("https://taleez.com/apply/sp/donecle", "donecle"),
])
def test_an_entry_is_a_slug_or_a_link(entry, slug):
    assert taleez._slug(entry) == slug


def test_the_feed_url_is_the_careez_list_of_the_tenant():
    assert taleez.feed_url("donecle") == "https://donecle.taleez.com/api/careez"
    assert taleez.feed_url("donecle.taleez.com") == "https://donecle.taleez.com/api/careez"


# --- the job list ---

def test_parse_list_gives_the_employer_and_its_jobs():
    name, jobs = taleez.parse_list(_fx("donecle_careez.json"))

    assert name == "Donecle"
    assert [j["id"] for j in jobs] == ["600922", "600692", "598975"]
    first = jobs[0]
    assert first["title"] == "Responsable RH (H/F)"
    assert first["slug"] == "responsable-rh-h-f-toulouse-donecle-cdi"
    assert first["url"] == "https://taleez.com/apply/responsable-rh-h-f-toulouse-donecle-cdi"
    assert first["location"] == "Toulouse, FR"
    assert first["posted_at"] == datetime(2026, 10, 12, 10, 17, 16, tzinfo=timezone.utc)


def test_parse_list_rejects_what_is_not_a_job_list():
    for text in ("<html>Erreur</html>", "", "[]", '{"jobs": "x"}', '{"name": "x"}'):
        with pytest.raises(ValueError):
            taleez.parse_list(text)


def test_an_employer_without_open_jobs_is_a_valid_empty_list():
    assert taleez.parse_list('{"name": "Acme", "jobs": []}') == ("Acme", [])


def test_a_job_without_id_slug_or_title_is_skipped():
    text = json.dumps({"name": "A", "jobs": [{"id": 1, "label": "T"}, {"slug": "s", "label": "T"}, {"id": 2, "slug": "s"},
                                             {"id": 3, "slug": "ok", "label": "Dev"}]})

    assert [j["id"] for j in taleez.parse_list(text)[1]] == ["3"]


@pytest.mark.parametrize("location,remote,text", [
    ({"city": "Lyon", "postalCode": "69001", "region": "Auvergne-Rhone-Alpes", "country": "FR"}, False, "Lyon, FR"),
    ({"city": "Lyon", "country": "FR"}, True, "Lyon, FR"),
    ({"city": "", "country": "FR"}, False, "FR"),
    ({"region": "Occitanie", "country": "FR"}, False, "Occitanie, FR"),
    (None, True, "Remote"),
    (None, False, ""),
    ({}, True, "Remote"),
])
def test_location_text(location, remote, text):
    assert taleez._location_text(location, remote) == text


def test_the_publish_date_is_milliseconds_with_the_creation_date_as_fallback():
    assert taleez._date({"publishDate": 1791800236000}) == datetime(2026, 10, 12, 10, 17, 16, tzinfo=timezone.utc)
    assert taleez._date({"creationDate": 1791799933000}).year == 2026
    assert taleez._date({"publishDate": "x"}) is None
    assert taleez._date({}) is None


# --- the ad ---

def test_parse_ad_reads_the_json_ld_description_and_qualifications():
    ad = taleez.parse_ad(_fx("ad_600692.html"))

    assert ad["description"].startswith("We are looking for a proactive Key Account Manager")
    assert "Fluent English" in ad["description"] and "<" not in ad["description"]
    assert ad["organization"] == "Donecle"


def test_parse_ad_of_a_page_without_the_snippet_is_none():
    assert taleez.parse_ad("<html><body>Erreur</body></html>") is None
    assert taleez.parse_ad("") is None
    assert taleez.parse_ad('<script id="jobPostingSnippet" type="application/ld+json">{oops</script>') is None


# --- detection ---

@pytest.mark.parametrize("url,entry", [
    ("https://donecle.taleez.com", "donecle"),
    ("https://donecle.taleez.com/en", "donecle"),
    ("https://forum-refugies.taleez.com/api/careez", "forum-refugies"),
    ("https://taleez.com/apply/sp/donecle", "donecle"),
])
def test_detect_url_names_the_tenant(url, entry):
    det = taleez.detect_url(url)
    assert det.platform == "taleez" and det.entry == entry


@pytest.mark.parametrize("url", [
    "https://taleez.com/apply/responsable-rh-h-f-toulouse-donecle-cdi",   # an ad: the job's slug names no tenant
    "https://taleez.com/",
    "https://www.taleez.com/tarifs",
    "https://app.taleez.com/login",
    "https://files.taleez.com/files/1.png",
    "https://a.b.taleez.com/",
    "https://example.com/taleez.com",
])
def test_detect_url_names_nothing_for_the_vendors_own_pages(url):
    assert taleez.detect_url(url) is None


def test_the_name_probe_tries_the_careez_list_of_the_slug():
    [probe] = taleez.name_probes("donecle")
    assert probe.url == "https://donecle.taleez.com/api/careez" and probe.key == taleez.FEED_KEY


def test_the_dispatcher_knows_taleez():
    assert "taleez" in ats_detect.PRECEDENCE
    assert ats_detect.from_url("https://donecle.taleez.com/en").platform == "taleez"
    assert ats_detect.from_cname("careers.donecle.com", "donecle.taleez.com").entry == "donecle"
    assert ats_detect.from_cname("careers.donecle.com", "www.taleez.com") is None

