"""Live smoke test per ad language: its language file still fits real ads written in it.

Opt-in (marked `live`): one small search per language on a source with ads in it, descriptions
included (one results page, one search). The rows are `tests/live_matrix.LANGUAGES`;
`scripts/smoke_report.py` lists each language's result on the status page, apart from the sites'.
"""

import pytest

from door import i18n
from live_matrix import LANGUAGES, module

_MIN_ADS = 3


@pytest.mark.live
@pytest.mark.parametrize("code", sorted(LANGUAGES))
def test_language_live(code, monkeypatch):
    run = LANGUAGES[code]
    scraper = module(run)
    for knob in ("_MAX_PAGES", "_MAX_SEARCHES"):  # one results page, one search: a sample, not a crawl
        if hasattr(scraper, knob):
            monkeypatch.setattr(scraper, knob, 1)
    config = {"location": run.city, "search_keywords": [run.keyword], "role_targets": [run.keyword],
              "max_pages_per_keyword": 1}
    texts = [p["description"] for p in scraper.scrape(config) if len(p.get("description") or "") >= 300]

    written = [text for text in texts if i18n.detect_language(text) == code]
    assert len(written) >= _MIN_ADS, (
        f"{len(written)} of {len(texts)} ads from {run.source} for {run.keyword!r} detected as {code}: "
        f"{[i18n.detect_language(t) for t in texts]}")

    words = i18n.compile_words([*i18n.heading_words("requirement", (code,)), *i18n.heading_words("responsibility", (code,)),
                                *i18n.marker_words("requirement", (code,))])
    assert any(words.search(text) for text in written), (
        f"none of the {code} language file's headings or requirement markers occur in {len(written)} real {code} ads")
