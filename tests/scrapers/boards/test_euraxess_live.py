"""Live smoke test for EURAXESS (issue #431): opt-in (`live`), the Danish offers over plain HTTP."""

import pytest

from door.scrapers import drain_errors, drain_pushback

from door.core.models import JobPosting
from door.scrapers.boards import euraxess
from live_utils import skip_if_refused_in_ci


_COUNTRIES = {"Copenhagen, Denmark": "Denmark", "Paris, France": "France", "Stockholm, Sweden": "Sweden",
              "London, United Kingdom": "United Kingdom"}


def _check(monkeypatch, location: str) -> None:
    monkeypatch.setattr(euraxess, "_MAX_PAGES", 1)   # one listing page a country: back-to-back runs hit the 429 (#579)
    drain_errors("euraxess")
    drain_pushback("euraxess")
    postings = euraxess.scrape({"search_keywords": ["postdoc"], "topic_terms": [], "location": location})
    errors = drain_errors("euraxess").get("euraxess", []) + (["pushback"] if drain_pushback("euraxess") else [])
    if not postings and errors:
        skip_if_refused_in_ci("euraxess", errors)
        pytest.fail("the EURAXESS listing did not load")
    if not postings:
        # When the server ignores the country facet, one worldwide page may hold none of this country's offers.
        pytest.skip(f"no {_COUNTRIES[location]} offer in the newest worldwide page")
    for p in postings[:5]:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"].startswith("https://euraxess.ec.europa.eu/jobs/")
        assert p["description"]
    for p in postings:
        assert p["location"].rsplit(",", 1)[-1].strip() == _COUNTRIES[location]


@pytest.mark.live
def test_euraxess_returns_valid_danish_postings(monkeypatch):
    _check(monkeypatch, "Copenhagen, Denmark")


@pytest.mark.live
def test_euraxess_returns_valid_french_postings(monkeypatch):
    _check(monkeypatch, "Paris, France")


@pytest.mark.live
def test_euraxess_returns_valid_swedish_postings(monkeypatch):
    _check(monkeypatch, "Stockholm, Sweden")


@pytest.mark.live
def test_euraxess_returns_valid_uk_postings(monkeypatch):
    _check(monkeypatch, "London, United Kingdom")
