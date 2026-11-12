"""Unit tests for the Recman helpers: entries, the sitemap, the JSON-LD ad and the feed detection."""

import json

import pytest
import responses

from door.scrapers.feeds import recman
from door.scrapers.sdk import PoliteSession
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "recman"


def _fx(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


def _page(**fields) -> str:
    ad = {"@type": "JobPosting", "title": "Dev", "description": "<p>Hej</p>", **fields}
    return f'<html><head><script type="application/ld+json">{json.dumps(ad)}</script></head></html>'


# --- entries ---

@pytest.mark.parametrize("entry,base", [
    ("pn", "https://pn.recman.page"),
    (" PN ", "https://pn.recman.page"),
    ("pn.recman.page", "https://pn.recman.page"),
    ("yourstaff.recman.io", "https://yourstaff.recman.io"),
    ("stillinger.signo.no", "https://stillinger.signo.no"),
    ("https://stillinger.signo.no/jobs", "https://stillinger.signo.no"),
])
def test_an_entry_is_a_slug_or_a_career_host(entry, base):
    assert recman._base(entry) == base


# --- the sitemap ---

def test_the_sitemap_lists_the_job_pages_and_nothing_else():
    jobs = recman._job_links(_fx("pn_sitemap.xml"))

    assert [j["id"] for j in jobs] == ["490875", "477333", "429148"]
    assert jobs[2]["url"] == "https://pn.recman.page/job/429148"


def test_a_page_that_is_no_sitemap_lists_no_jobs():
    assert recman._job_links(_fx("unknown.html")) == []
    assert recman._is_sitemap(_fx("pn_sitemap.xml")) and not recman._is_sitemap(_fx("unknown.html"))


# --- the ad ---

def test_an_ad_is_read_from_its_json_ld():
    ad = recman._parse_detail(_fx("pn_429148.html"))

    assert ad["title"] == "Elektronikingenjör till ShortLink!"
    assert ad["location"] == "Linköping, SE"
    assert ad["posted_at"] == "2025-04-29"
    assert ad["organization"] == "Professionals Nord Rekrytering AB"
    assert "<" not in ad["description"] and "FPGA" in ad["description"]


def test_an_english_ad_and_its_blanks():
    ad = recman._parse_detail(_fx("personell_469566.html"))

    assert ad["title"] == "We're looking for Cost Controller"
    assert ad["location"] == "" and "cost controllers" in ad["description"]


def test_a_postal_code_alone_is_no_place():
    assert recman._parse_detail(_fx("pn_490875.html"))["location"] == ""


@pytest.mark.parametrize("place,text", [
    ({"address": {"addressLocality": "Lund", "addressCountry": "SE"}}, "Lund, SE"),
    ({"address": {"addressLocality": "Oslo"}}, "Oslo"),
    ([{"address": {"addressLocality": "Lund", "addressCountry": "SE"}}, {"address": {"addressLocality": "Malmö"}}],
     "Lund, SE; Malmö"),
    ({"address": {"addressCountry": "NO"}}, "NO"),
    (None, ""),
    ("Lund", ""),
])
def test_a_location_is_the_locality_and_country_of_each_place(place, text):
    assert recman._location_text(place) == text


def test_a_title_has_its_spaces_collapsed():
    assert recman._parse_detail(_page(title="We're  looking for Dev"))["title"] == "We're looking for Dev"


@pytest.mark.parametrize("html", ["", "<html></html>", _page(**{"@type": "Organization"}), "<script type=\"application/ld+json\">{bad</script>",
                                  _page(title="")])
def test_a_page_with_no_ad_is_none(html):
    assert recman._parse_detail(html) is None


def test_an_ad_among_several_json_ld_blocks_is_found():
    other = '<script type="application/ld+json">{"@type": "WebSite"}</script>'
    assert recman._parse_detail(other + _page(title="Svetsare"))["title"] == "Svetsare"


def test_a_graph_wrapper_is_looked_through():
    graph = {"@graph": [{"@type": "WebSite"}, {"@type": "JobPosting", "title": "Tekniker", "description": "x"}]}
    html = f'<script type="application/ld+json">{json.dumps(graph)}</script>'
    assert recman._parse_detail(html)["title"] == "Tekniker"


# --- feed detection ---

@pytest.mark.parametrize("url,entry", [
    ("https://pn.recman.page/job/429148", "pn"),
    ("https://PN.recman.page/jobs?x=1", "pn"),
    ("pn.recman.page", "pn"),
    ("https://yourstaff.recman.io/jobs", "yourstaff.recman.io"),
])
def test_a_tenant_link_names_its_entry(url, entry):
    det = recman.detect_url(url)

    assert det.platform == "recman" and det.entry == entry


@pytest.mark.parametrize("url", [
    "https://example.invalid/x", "https://www.recman.io/", "https://help.recman.io/hc/en-us", "https://developers.recman.io/",
    "https://cdn.recman.io/drive/logo/1.png", "https://recman.page/", "https://notrecman.page/job/1",
])
def test_other_links_are_not_a_tenant(url):
    assert recman.detect_url(url) is None


def test_an_apply_link_names_no_tenant_until_it_is_followed():
    det = recman.detect_url("https://apply.recman.page/job_post.php?id=429148&sub_id=985&path=ams")

    assert det.platform == "recman" and det.entry is None and det.refusal == "cant_yet"


def test_the_shared_apply_host_alone_is_not_a_detection():
    assert recman.detect_url("https://apply.recman.page/") is None
    assert recman.detect_url("https://apply.recman.page/unknown") is None


def test_the_feed_needs_no_confirmation():
    assert recman.feed_url("pn") is None
    assert recman.name_probes("pn") == []


def test_a_cname_for_a_tenant_names_it():
    det = recman.detect_cname("stillinger.signo.no", "signo.recman.page", "where")

    assert det.entry == "signo" and det.evidence == "where"
    assert recman.detect_cname("x.example.com", "x.example.net", "w") is None
    assert recman.detect_cname("x.example.com", "apply.recman.page", "w") is None


def test_the_page_of_a_career_site_on_the_employers_host_is_recognised():
    html = '<title>Platsannonser</title><script src="https://cp-analytics.recman.io"></script>'
    det = recman.detect_html(html, "https://personell.seie.no/jobs")

    assert det.entry == "personell.seie.no"
    assert recman.detect_html("<html>nothing</html>", "https://x.example.com") is None


# --- resolve: an apply link is followed to the host it redirects to ---

def _session():
    return PoliteSession(min_delay=0, max_delay=0, timeout=5, max_retries=0)


_APPLY = "https://apply.recman.page/job_post.php?id=429148&path=ams&sub_id=985"


@responses.activate
def test_an_apply_link_resolves_to_the_tenant_it_redirects_to():
    responses.add(responses.GET, _APPLY, status=302, headers={"Location": "https://pn.recman.page/job/429148?path=ams"})
    responses.add(responses.GET, "https://pn.recman.page/job/429148?path=ams", body="<html></html>")

    det = recman.resolve(_session(), recman.detect_url(_APPLY), _APPLY)

    assert det.entry == "pn" and "pn.recman.page" in det.evidence


@responses.activate
def test_an_apply_link_resolves_to_the_employers_own_career_host():
    responses.add(responses.GET, _APPLY, status=302, headers={"Location": "https://stillinger.signo.no/job/1?path=nav"})
    responses.add(responses.GET, "https://stillinger.signo.no/job/1?path=nav", body="<html></html>")

    assert recman.resolve(_session(), recman.detect_url(_APPLY), _APPLY).entry == "stillinger.signo.no"


@responses.activate
def test_an_apply_link_that_lands_on_the_shared_host_stays_unfollowable():
    responses.add(responses.GET, _APPLY, status=302, headers={"Location": "https://apply.recman.page/unknown"})
    responses.add(responses.GET, "https://apply.recman.page/unknown", body=_fx("unknown.html"))
    det = recman.detect_url(_APPLY)

    assert recman.resolve(_session(), det, _APPLY) == det


@responses.activate
def test_an_apply_link_that_cannot_be_read_stays_as_it_was():
    responses.add(responses.GET, _APPLY, status=500)
    det = recman.detect_url(_APPLY)

    assert recman.resolve(_session(), det, _APPLY) == det


def test_a_tenant_detection_is_left_alone_by_resolve():
    det = recman.detect_url("https://pn.recman.page/jobs")

    assert recman.resolve(_session(), det, "https://pn.recman.page/jobs") == det
