"""Unit tests for the Recruitee careers API's pure helpers (issue #231)."""

import pytest

from door.scrapers.feeds import recruitee


@pytest.mark.parametrize("entry, base", [
    ("famly", "https://famly.recruitee.com"),
    (" Famly ", "https://famly.recruitee.com"),
    ("https://famly.recruitee.com/o/senior-engineer", "https://famly.recruitee.com"),
    ("famly.recruitee.com", "https://famly.recruitee.com"),
    ("careers.trackman.com", "https://careers.trackman.com"),
])
def test_careers_base_accepts_a_slug_or_a_careers_host(entry, base):
    assert recruitee._careers_base(entry) == base


@pytest.mark.parametrize("raw, iso", [
    ("2026-09-11 13:08:03 UTC", "2026-09-11T13:08:03+00:00"),
    ("2026-09-11T13:08:03Z", "2026-09-11T13:08:03+00:00"),
])
def test_parse_date(raw, iso):
    assert recruitee._parse_date(raw).isoformat() == iso


@pytest.mark.parametrize("raw", [None, "", "soon"])
def test_parse_date_rejects_what_is_not_a_date(raw):
    assert recruitee._parse_date(raw) is None


def test_location_text_marks_remote_and_hybrid_work():
    offer = {"city": "Copenhagen", "country": "Denmark", "location": "Copenhagen, Hovedstaden, Denmark"}
    assert recruitee._location_text(offer) == "Copenhagen, Hovedstaden, Denmark"
    assert recruitee._location_text({**offer, "remote": True}) == "Remote, Copenhagen, Hovedstaden, Denmark"
    assert recruitee._location_text({"city": "Aarhus", "country": "Denmark"}) == "Aarhus, Denmark"
    assert recruitee._location_text({"remote": True}) == "Remote"

# --- feed detection (issue #282) ---

def _d(det):
    return None if det is None else (det.platform, det.entry)


def test_detect_url():
    assert _d(recruitee.detect_url("https://famly.recruitee.com/o/senior-engineer")) == ("recruitee", "famly")
    assert recruitee.detect_url("https://careers.recruitee.com/o/x") is None
    assert recruitee.detect_url("https://recruitee.com/") is None


def test_detect_cname_and_html():
    assert _d(recruitee.detect_cname("careers.veo.co", "secure.recruitee.com", "w")) == ("recruitee", "careers.veo.co")
    assert recruitee.detect_cname("careers.veo.co", "acme.github.io", "w") is None
    """careers.trackman.com runs on Recruitee: its page names trackman.recruitee.com and its CDN."""
    html = '{"apiHost":"https://api.recruitee.com","assetHost":"https://x.recruiteecdn.com"} trackman.recruitee.com'
    assert _d(recruitee.detect_html(html, "https://careers.trackman.com/")) == ("recruitee", "careers.trackman.com")
    assert recruitee.detect_html('<a href="https://recruitee.com/">x</a>', "https://careers.acme.dk/") is None


def test_the_feed_of_an_entry_is_its_offers_api():
    assert recruitee.feed_url("famly") == "https://famly.recruitee.com/api/offers/"
    assert recruitee.feed_url("careers.trackman.com") == "https://careers.trackman.com/api/offers/"
    assert recruitee.FEED_KEY == "offers"
    (probe,) = recruitee.name_probes("acme")
    assert (probe.url, probe.key) == ("https://acme.recruitee.com/api/offers/", "offers")
