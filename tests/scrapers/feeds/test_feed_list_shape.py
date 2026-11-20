"""A feed's scrape and its probe read the job list through one extractor, so a bad answer reads the same in both."""

import pytest

from door.scrapers.feeds import ashby, greenhouse, lever, pinpoint, recruitee, teamtailor

_EXTRACTORS = [
    (greenhouse._job_list, {"jobs": [{"id": 1}]}, "jobs"),
    (ashby._job_list, {"jobs": [{"id": 1}]}, "jobs"),
    (pinpoint._data_list, {"data": [{"id": 1}]}, "data"),
    (recruitee._offer_list, {"offers": [{"id": 1}]}, "offers"),
    (teamtailor._item_list, {"items": [{"id": 1}]}, "items"),
    (lever._job_list, [{"id": 1}], "postings"),
]


@pytest.mark.parametrize("extract, good, word", _EXTRACTORS)
def test_the_extractor_returns_the_list(extract, good, word):
    assert extract(good) == (good if isinstance(good, list) else next(iter(good.values())))


@pytest.mark.parametrize("extract, good, word", _EXTRACTORS)
@pytest.mark.parametrize("bad", [None, "text", 3, {}, {"other": []}, {"jobs": "x", "data": "x", "offers": "x", "items": "x"}])
def test_the_extractor_names_the_missing_list(extract, good, word, bad):
    if isinstance(good, list) and not isinstance(bad, list):
        pass
    with pytest.raises(ValueError, match=word):
        extract(bad)
