"""Unit tests for The Hub pure helpers (C4, unit layer) — Nuxt SSR payloads.

Covers _location_text, _job_url, _parse_date, _country_code,
_parse_listing_payload, _parse_detail_payload and the `window.__NUXT__` extraction
and evaluation (_nuxt_script, _evaluate_nuxt, _nuxt_state).
Pure and offline.
"""

import json
from pathlib import Path

import pytest

from door.core import sites
from door.scrapers.boards import thehub

_FIX = Path(__file__).parent / "fixtures" / "thehub"


def _fx(name: str) -> dict:
    return json.loads((_FIX / name).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# _location_text  (node: {"location": {address, locality, country}, isRemote})
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "node,expected",
    [
        ({"location": {"address": "Copenhagen, Denmark"}}, "Copenhagen, Denmark"),
        ({"location": {"locality": "Aarhus", "country": "Denmark"}}, "Aarhus, Denmark"),
        ({"location": {"country": "Denmark"}}, "Denmark"),
        ({"location": {}}, ""),
        ({"location": {"address": "Copenhagen"}, "isRemote": True}, "Copenhagen (Remote)"),
        ({"isRemote": True}, "Remote"),
    ],
)
def test_location_text(node, expected):
    assert thehub._location_text(node) == expected


# --------------------------------------------------------------------------- #
# _job_url
# --------------------------------------------------------------------------- #

def test_job_url_builds_canonical_id_based_url():
    assert thehub._job_url("6aa1f3cc961a30471ccb36b8") == "https://thehub.io/jobs/6aa1f3cc961a30471ccb36b8"


# --------------------------------------------------------------------------- #
# _parse_date
# --------------------------------------------------------------------------- #

def test_parse_date_iso_with_z_and_millis():
    dt = thehub._parse_date("2026-05-29T11:36:28.470Z")
    assert dt is not None and dt.year == 2026 and dt.month == 5


@pytest.mark.parametrize("bad", [None, "not-a-date"])
def test_parse_date_invalid_returns_none(bad):
    assert thehub._parse_date(bad) is None


# --------------------------------------------------------------------------- #
# _country_code
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("location", ["Copenhagen", "Frederiksberg", "Denmark", "Danmark"])
def test_country_code_without_the_engine_key_comes_from_the_location(location):
    """The probe path (`doctor`, `scraper_fix`) skips `_scrape_core`, so no `_country`."""
    assert thehub._country_code({"location": location}) == "DK"


def test_country_code_comes_from_the_engine_resolved_country():
    assert thehub._country_code({"_country": "dk"}) == "DK"


def test_country_code_of_a_country_the_site_does_not_serve_is_its_first():
    """The Hub is registered for Denmark only, so anywhere else searches Denmark."""
    assert thehub._country_code({"location": "Stockholm"}) == "DK"
    assert thehub._country_code({"_country": "se"}) == "DK"
    assert thehub._country_code({"_country": None}) == "DK"


def test_the_served_countries_match_the_registry():
    assert thehub._SERVED == tuple(sites.SITES["thehub"].countries)


# --------------------------------------------------------------------------- #
# _parse_listing_payload
# --------------------------------------------------------------------------- #

def test_parse_listing_payload_first_page_has_next():
    docs, has_next = thehub._parse_listing_payload(_fx("listing_page1.json"))
    assert len(docs) == 2
    assert docs[0]["id"] == "6aa1f3cc961a30471ccb36b8"
    assert has_next is True


# --------------------------------------------------------------------------- #
# _parse_detail_payload
# --------------------------------------------------------------------------- #

def test_parse_detail_payload_maps_fields():
    parsed = thehub._parse_detail_payload(_fx("detail_flatpay.json"))
    assert parsed is not None
    assert parsed["title"] == "Data Scientist"
    assert parsed["company"] == "Flatpay"
    assert parsed["location"] == "Copenhagen, Denmark"
    assert "<" not in parsed["description"]
    assert "growing AI team" in parsed["description"]
    assert parsed["posted_at"] is not None
    assert parsed["posted_at"].year == 2026 and parsed["posted_at"].month == 9


def test_parse_detail_payload_apply_url_is_the_link():
    assert thehub._parse_detail_payload(_fx("detail_lunar.json"))["apply_url"] == "https://lunar.app/careers/senior-data-scientist"


def test_parse_detail_payload_without_a_link_has_no_apply_url():
    # Live ads that are applied to by email carry `link: ""` or no `link` at all.
    job = {**_fx("detail_lunar.json"), "link": ""}
    assert thehub._parse_detail_payload(job)["apply_url"] is None
    job.pop("link")
    assert thehub._parse_detail_payload(job)["apply_url"] is None


def test_parse_detail_payload_strips_company_name_whitespace():
    parsed = thehub._parse_detail_payload({
        "id": "abc123",
        "key": "k",
        "title": "Envira job",
        "company": {"name": "Envira "},
        "location": {"address": "Copenhagen, Denmark"},
        "isRemote": False,
        "description": "<p>hello</p>",
        "publishedAt": None,
    })
    assert parsed is not None
    assert parsed["company"] == "Envira"
    assert parsed["posted_at"] is None


def test_parse_detail_payload_returns_none_for_empty_job():
    assert thehub._parse_detail_payload({}) is None


# --------------------------------------------------------------------------- #
# window.__NUXT__ extraction and evaluation
# --------------------------------------------------------------------------- #

_IIFE = "(function(a,b){return {state:{jobs:{job:{id:a,title:b}}}}}(\"x1\",\"T\"))"


def test_nuxt_script_takes_the_expression_after_the_assignment():
    html = f"<html><script>var x=1;</script><script>window.__NUXT__={_IIFE};</script><script>y()</script></html>"
    assert thehub._nuxt_script(html) == _IIFE


def test_nuxt_script_none_without_the_assignment():
    assert thehub._nuxt_script("<html><script>var x=1;</script></html>") is None
    assert thehub._nuxt_script("window.__NUXT__=(1)") is None  # no closing tag


def test_evaluate_nuxt_runs_the_iife_and_returns_the_object():
    assert thehub._evaluate_nuxt(_IIFE) == {"state": {"jobs": {"job": {"id": "x1", "title": "T"}}}}


def test_evaluate_nuxt_has_no_dom_or_network():
    for expr in ("(function(){return {w: typeof window, d: typeof document, f: typeof fetch, x: typeof XMLHttpRequest}}())",):
        assert thehub._evaluate_nuxt(expr) == {"w": "undefined", "d": "undefined", "f": "undefined", "x": "undefined"}


@pytest.mark.parametrize("expr", [
    "(function(){throw new Error('boom')}())",
    "(function(){return a.b.c}())",
    "(function({",  # syntax error
    "(function(){return 5}())",  # not an object
    "(function(){return undefined}())",
])
def test_evaluate_nuxt_raises_value_error_on_failure(expr):
    with pytest.raises(ValueError):
        thehub._evaluate_nuxt(expr)


def test_evaluate_nuxt_stops_a_runaway_script():
    with pytest.raises(ValueError):
        thehub._evaluate_nuxt("(function(){while(true){}}())")


def test_nuxt_state_walks_the_path():
    html = f"<script>window.__NUXT__={_IIFE};</script>"
    assert thehub._nuxt_state(html, ("state", "jobs", "job")) == {"id": "x1", "title": "T"}
    assert thehub._nuxt_state(html, ("state", "jobs", "jobs")) is None


def test_nuxt_state_without_nuxt_raises():
    with pytest.raises(ValueError, match="__NUXT__"):
        thehub._nuxt_state("<html></html>", ("state",))
