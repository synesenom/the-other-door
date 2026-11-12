"""Unit tests for the Flatchr feed's pure helpers."""

from datetime import datetime, timezone

import pytest

from door.scrapers.feeds import flatchr

_NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize("entry, slug", [
    ("flatchr", "flatchr"),
    (" Flatchr ", "flatchr"),
    ("flatchr.flatchr.io", "flatchr"),
    ("https://acme.flatchr.io/", "acme"),
    ("https://careers.flatchr.io/fr/company/acme/vacancy/abc-dev", "acme"),
    ("careers.flatchr.io/company/acme.json", "acme"),
    ("https://careers.flatchr.io/", None),
    ("careers.acme.com", None),
    ("", None),
])
def test_slug_accepts_a_slug_a_host_or_a_link(entry, slug):
    assert flatchr._slug(entry) == slug


def test_feed_url_is_the_company_json():
    assert flatchr.feed_url("flatchr") == "https://careers.flatchr.io/company/flatchr.json"
    assert flatchr.feed_url("https://acme.flatchr.io") == "https://careers.flatchr.io/company/acme.json"
    assert flatchr.feed_url("careers.acme.com") is None


def test_name_probes_try_the_slug_of_a_name():
    (probe,) = flatchr.name_probes("acme")
    assert probe.url == "https://careers.flatchr.io/company/acme.json" and probe.key == "items"


def test_location_text_is_city_and_country():
    assert flatchr._location_text({"address": {"locality": "Lyon", "country": "France"}}) == "Lyon, France"
    assert flatchr._location_text({"address": {"locality": "Lyon"}}) == "Lyon"
    assert flatchr._location_text({"address": {"country": "France"}}) == "France"
    assert flatchr._location_text({"address": None}) == ""
    assert flatchr._location_text({}) == ""


def test_description_joins_the_three_html_parts_as_text():
    text = flatchr._description({"description": "<p>Intro</p>", "mission": "<h2>Role</h2><ul><li>A</li></ul>",
                                 "profile": None})
    assert "<" not in text and text.index("Intro") < text.index("Role") < text.index("A")


def test_to_posting_maps_a_vacancy():
    item = {"vacancy": {"vacancy_id": 12, "slug": "x1-dev", "title": " Dev ", "description": "<p>d</p>",
                        "created_at": "2026-10-09T07:56:42.594Z", "language": "fr_FR",
                        "address": {"locality": "Paris", "country": "France"}, "company": {"name": "Acme SAS"}}}

    posting = flatchr._to_posting(item, "acme", "", _NOW)

    assert posting["id"] == "flatchr.12" and posting["platform_id"] == "12"
    assert posting["title"] == "Dev" and posting["company"] == "Acme SAS"
    assert posting["url"] == "https://careers.flatchr.io/fr/company/acme/vacancy/x1-dev"
    assert posting["posted_at"].startswith("2026-10-09") and posting["location"] == "Paris, France"
    assert flatchr._to_posting(item, "acme", "Acme", _NOW)["company"] == "Acme"  # the followed name wins


def test_items_keeps_only_vacancies_with_an_id_and_title():
    data = {"items": [{"vacancy": {"vacancy_id": 1, "title": "A"}}, {"vacancy": {"title": "B"}}, {"x": 1}, "y"]}
    assert [i["vacancy"]["title"] for i in flatchr._items(data)] == ["A"]
    assert flatchr._items({"statusCode": 404}) is None


# --- feed detection (issue #282) ---

def _d(det):
    return None if det is None else (det.platform, det.entry)


def test_detect_url():
    assert _d(flatchr.detect_url("https://careers.flatchr.io/fr/company/acme/vacancy/abc-dev")) == ("flatchr", "acme")
    assert _d(flatchr.detect_url("https://careers.flatchr.io/company/acme")) == ("flatchr", "acme")
    assert _d(flatchr.detect_url("https://acme.flatchr.io/")) == ("flatchr", "acme")
    assert flatchr.detect_url("https://careers.flatchr.io/") is None
    assert flatchr.detect_url("https://www.flatchr.io/cgu") is None
    assert flatchr.detect_url("https://app.flatchr.io/login") is None
    assert flatchr.detect_url("https://example.invalid/x") is None


def test_detect_html_and_cname():
    html = '<a href="https://careers.flatchr.io/fr/company/acme/vacancy/x">Postuler</a>'
    assert _d(flatchr.detect_html(html, "https://acme.fr/carrieres")) == ("flatchr", "acme")
    assert flatchr.detect_html("<p>nothing</p>", "https://acme.fr") is None
    assert _d(flatchr.detect_cname("emploi.acme.fr", "acme.flatchr.io", "CNAME")) == ("flatchr", "acme")
    assert flatchr.detect_cname("emploi.acme.fr", "x.example.com", "CNAME") is None
