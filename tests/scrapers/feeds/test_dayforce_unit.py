"""Unit tests for the Dayforce candidate portal's pure helpers."""

import pytest

from door.scrapers.feeds import dayforce


@pytest.mark.parametrize("entry, expected", [
    ("natus/CANDIDATEPORTALSENSORY", ("natus", "CANDIDATEPORTALSENSORY")),
    (" Natus/CANDIDATEPORTALSENSORY/ ", ("natus", "CANDIDATEPORTALSENSORY")),
    ("https://jobs.dayforcehcm.com/en-US/natus/CANDIDATEPORTALSENSORY/jobs/3288", ("natus", "CANDIDATEPORTALSENSORY")),
    ("https://jobs.dayforcehcm.com/natus/CANDIDATEPORTALSENSORY/jobs/3288", ("natus", "CANDIDATEPORTALSENSORY")),
    ("jobs.dayforcehcm.com/zh-Hans-SG/acme/External", ("acme", "External")),
    ("jobs.dayforcehcm.com/en-US/acme/External", ("acme", "External")),
])
def test_portal_accepts_an_id_or_a_portal_link(entry, expected):
    assert dayforce._portal(entry) == expected


@pytest.mark.parametrize("entry", ["natus", "", "https://jobs.dayforcehcm.com/en-US"])
def test_portal_rejects_what_names_no_portal(entry):
    assert dayforce._portal(entry) is None


def test_location_text_joins_the_posting_locations():
    posting = {"postingLocations": [{"formattedAddress": "Bengaluru, Karnataka, India"},
                                    {"formattedAddress": "Texas, USA"}, {"formattedAddress": "Texas, USA"}]}
    assert dayforce._location_text(posting) == "Bengaluru, Karnataka, India; Texas, USA"
    assert dayforce._location_text({**posting, "hasVirtualLocation": True}).startswith("Remote; ")
    assert dayforce._location_text({"hasVirtualLocation": True}) == "Remote"
    assert dayforce._location_text({}) == ""

# --- feed detection (issue #282) ---

def _d(det):
    return None if det is None else (det.platform, det.entry)


@pytest.mark.parametrize("url, entry", [
    ("https://jobs.dayforcehcm.com/en-US/natus/CANDIDATEPORTALSENSORY/jobs/3288", "natus/CANDIDATEPORTALSENSORY"),
    ("https://jobs.dayforcehcm.com/natus/CANDIDATEPORTALSENSORY/jobs/3288", "natus/CANDIDATEPORTALSENSORY"),
    ("https://jobs.dayforcehcm.com/en-US/natus/CANDIDATEPORTALSENSORY", "natus/CANDIDATEPORTALSENSORY"),
    ("https://jobs.dayforcehcm.com/zh-Hans-SG/Acme/External", "acme/External"),
])
def test_detect_url_reads_the_portal(url, entry):
    assert _d(dayforce.detect_url(url)) == ("dayforce", entry)


def test_a_link_without_a_portal_is_not_a_feed():
    assert dayforce.detect_url("https://jobs.dayforcehcm.com/en-US") is None
    assert dayforce.detect_url("https://jobs.dayforcehcm.com/") is None
    assert dayforce.detect_url("https://example.com/en-US/natus/PORTAL") is None
    assert dayforce.feed_url("natus/PORTAL") is None
