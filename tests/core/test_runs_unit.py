"""Reading a run record (`jobs/runs/<timestamp>.json`)."""

from door.core import runs

SITE = {"site": "jobindex", "outcome": "ok", "count": 3}
FEED = {"site": "lever", "outcome": "failed", "count": 0, "errors": ["x"]}


def test_site_entries_are_the_search_and_collect_blocks_in_that_order():
    record = {"search": {"sites": [SITE]}, "discover": {"employers": 4}, "collect": {"sites": [FEED]}, "match": {}}
    assert runs.site_entries(record) == [SITE, FEED]


def test_steps_that_did_not_run_are_none_or_absent():
    assert runs.site_entries({"search": None, "collect": {"sites": [FEED]}}) == [FEED]
    assert runs.site_entries({}) == []


def test_postings_scraped_counts_the_ok_sites_of_both_steps():
    record = {"search": {"sites": [SITE, {"site": "x", "outcome": "error"}]}, "collect": {"sites": [{"site": "lever", "outcome": "ok", "count": 7}]}}
    assert runs.postings_scraped(record) == 10


def test_scored_reads_the_match_block():
    assert runs.scored({"match": {"scored": 12}}) == 12
    assert runs.scored({"match": None}) == 0
