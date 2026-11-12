"""Unit tests for the Pinpoint postings feed's pure helpers."""

import pytest

from door.scrapers.feeds import pinpoint


@pytest.mark.parametrize("entry, base", [
    ("factbird", "https://factbird.pinpointhq.com"),
    (" Factbird ", "https://factbird.pinpointhq.com"),
    ("https://factbird.pinpointhq.com/en/postings/abc", "https://factbird.pinpointhq.com"),
    ("factbird.pinpointhq.com", "https://factbird.pinpointhq.com"),
    ("careers.acme.com", "https://careers.acme.com"),
])
def test_careers_base_accepts_a_slug_or_a_careers_host(entry, base):
    assert pinpoint._careers_base(entry) == base


def test_location_text_marks_remote_and_hybrid_work():
    loc = {"city": "Copenhagen", "name": "Copenhagen "}
    assert pinpoint._location_text({"location": loc, "workplace_type": "onsite"}) == "Copenhagen"
    assert pinpoint._location_text({"location": loc, "workplace_type": "remote"}) == "Remote, Copenhagen"
    assert pinpoint._location_text({"location": loc, "workplace_type": "hybrid"}) == "Hybrid, Copenhagen"
    remote_us = {"location": {"city": "Remote", "name": "United States"}, "workplace_type": "remote"}
    assert pinpoint._location_text(remote_us) == "Remote, United States"
    assert pinpoint._location_text({"location": {"city": "Aarhus", "name": ""}}) == "Aarhus"
    assert pinpoint._location_text({"workplace_type": "remote"}) == "Remote"
    assert pinpoint._location_text({}) == ""

# --- feed detection (issue #282) ---

def _d(det):
    return None if det is None else (det.platform, det.entry)


def test_detect_url():
    assert _d(pinpoint.detect_url("https://factbird.pinpointhq.com/en/postings/996b5103")) == ("pinpoint", "factbird")
    assert pinpoint.detect_url("https://a.b.pinpointhq.com/x") is None


def test_the_feed_of_an_entry_is_its_postings_json_under_the_pinpoint_domain():
    assert pinpoint.feed_url("factbird") == "https://factbird.pinpointhq.com/postings.json"
    assert pinpoint.feed_url("careers.acme.com") == "https://careers.acme.com/postings.json"
    assert pinpoint.FEED_KEY == "data"
    (probe,) = pinpoint.name_probes("acme")
    assert probe.url == "https://acme.pinpointhq.com/postings.json" and probe.evidence == "Pinpoint site acme"
