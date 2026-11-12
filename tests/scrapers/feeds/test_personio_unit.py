"""Unit tests for Personio's pure helpers (issue #558)."""

import pytest

from door.scrapers.feeds import personio
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "personio"


def _read() -> str:
    return (_FX / "pno-group-europe.xml").read_text(encoding="utf-8")


@pytest.mark.parametrize("entry, host", [
    ("pno-group-europe", "pno-group-europe.jobs.personio.com"),
    (" PNO-Group-Europe ", "pno-group-europe.jobs.personio.com"),
    ("acme.jobs.personio.de", "acme.jobs.personio.de"),
    ("https://acme.jobs.personio.com/job/123?language=en", "acme.jobs.personio.com"),
])
def test_host_accepts_a_slug_a_host_or_a_link(entry, host):
    assert personio._host(entry) == host


def test_feed_urls():
    assert personio.xml_url("acme") == "https://acme.jobs.personio.com/xml"
    assert personio.xml_url("acme.jobs.personio.de") == "https://acme.jobs.personio.de/xml"


@pytest.mark.parametrize("url, entry", [
    ("https://pno-group-europe.jobs.personio.com/job/2803716", "pno-group-europe"),
    ("https://acme.jobs.personio.com/", "acme"),
    ("https://acme.jobs.personio.de/job/55?language=de", "acme.jobs.personio.de"),
    ("http://acme.jobs.personio.de/xml", "acme.jobs.personio.de"),
])
def test_detect_url_names_the_account(url, entry):
    det = personio.detect_url(url)
    assert det.platform == "personio" and det.entry == entry


@pytest.mark.parametrize("url", [
    "https://www.personio.com/",
    "https://jobs.personio.com/",
    "https://app.jobs.personio.com/",
    "https://acme.com/careers",
    "https://example.invalid/x",
])
def test_detect_url_ignores_what_is_no_account(url):
    assert personio.detect_url(url) is None


def test_the_feed_is_xml_so_it_is_confirmed_by_the_host():
    assert personio.feed_url("acme") is None
    assert personio.alive_url("acme") == "https://acme.jobs.personio.com/xml"


def test_a_custom_page_that_embeds_a_personio_board_is_detected():
    html = '<script src="https://acme.jobs.personio.com/widget.js"></script>'
    det = personio.detect_html(html, "https://acme.com/careers")
    assert det.platform == "personio" and det.entry == "acme"
    assert personio.detect_html("<html>nothing</html>", "https://acme.com") is None


def test_the_feed_is_read_into_ads():
    ads = personio.parse_feed(_read())
    assert [a["id"] for a in ads] == ["2803716", "1401049", "2185891", "2461874", "2754179"]
    first = ads[0]
    assert first["title"] == "Administrative Assistant"
    assert first["subcompany"] == "PNO Consultants SAS (France)"
    assert first["location"] == "Paris, France"
    assert first["posted_at"].isoformat().startswith("2026-09-18T14:43:10")
    assert first["description"].startswith("We need an administrative assistant for our Paris office.")
    assert "Keep contracts and files up to date." in first["description"]
    assert "<" not in first["description"]
    assert first["employment"] == "permanent / experienced / full-time"


def test_a_feed_without_positions_is_empty_not_an_error():
    assert personio.parse_feed('<?xml version="1.0"?>\n<workzag-jobs>\n</workzag-jobs>') == []


@pytest.mark.parametrize("text", ["<!DOCTYPE html><html><body>Page Not Found</body></html>", "", "not xml <"])
def test_a_page_that_is_not_the_feed_is_an_error(text):
    with pytest.raises(ValueError):
        personio.parse_feed(text)


def test_location_lists_cities_then_the_country():
    xml = ("<workzag-jobs><position><id>1</id><name>X</name><office>Netherlands</office><additionalOffices>"
           "<office>Groningen</office><office>Maastricht</office></additionalOffices></position></workzag-jobs>")
    assert personio.parse_feed(xml)[0]["location"] == "Groningen, Maastricht, Netherlands"
    bare = "<workzag-jobs><position><id>1</id><name>X</name><office>Berlin</office></position></workzag-jobs>"
    assert personio.parse_feed(bare)[0]["location"] == "Berlin"


def test_an_html_entity_in_a_title_is_decoded_once():
    xml = "<workzag-jobs><position><id>1</id><name>R&amp;D Consultant</name></position></workzag-jobs>"
    assert personio.parse_feed(xml)[0]["title"] == "R&D Consultant"


def test_a_posting_takes_the_followed_name_then_the_subcompany_then_the_account():
    from datetime import datetime, timezone

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ad = personio.parse_feed(_read())[0]
    host = "pno-group-europe.jobs.personio.com"
    named = personio._to_posting(ad, host, now, "PNO Group")
    assert named["company"] == "PNO Group"
    assert named["id"] == "personio.2803716" and named["platform_id"] == "2803716"
    assert named["url"] == "https://pno-group-europe.jobs.personio.com/job/2803716"
    assert named["apply_url"] == named["url"]
    assert personio._to_posting(ad, host, now)["company"] == "PNO Consultants SAS (France)"
    assert personio._to_posting({**ad, "subcompany": ""}, host, now)["company"] == "pno-group-europe"
