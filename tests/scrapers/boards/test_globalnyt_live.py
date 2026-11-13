"""Live smoke test for Globalnyt (smoke layer). Opt-in (marked `live`): reads the real ad list and the first ad pages."""

import pytest

from door.scrapers.boards import globalnyt
from live_utils import assert_field_contract


@pytest.mark.live
def test_globalnyt_returns_valid_postings():
    config = {"search_keywords": ["rådgiver"], "location": "Copenhagen"}
    postings = globalnyt.scrape(config)

    assert len(postings) >= 1
    assert_field_contract("globalnyt", postings, config)
    assert all(p["url"].startswith("https://globalnyt.dk/stilling/") for p in postings)
    assert any(p["company"] != "Globalnyt" for p in postings), "the employer should come from the ad page"
