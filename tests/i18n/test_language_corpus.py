"""Each language file still fits real ads written in it (#19): a few ads with their descriptions from a source
with ads in the language, saved by `scripts/refresh_corpus.py` (`tests/i18n/corpus/languages/<code>.json`).
Offline: a site's bad day never fails it; the site's own live test checks that it still answers."""

import pytest

from corpus_utils import load
from door import i18n
from live_matrix import LANGUAGES

_MIN_ADS = 3


@pytest.mark.parametrize("code", sorted(LANGUAGES))
def test_the_language_file_fits_its_saved_ads(code):
    run, saved = LANGUAGES[code], load("languages", code)
    assert saved["source"] == run.source, "refresh the corpus: its row changed"
    texts = saved["texts"]

    written = [text for text in texts if i18n.detect_language(text) == code]
    assert len(written) >= _MIN_ADS, (
        f"{len(written)} of {len(texts)} saved ads from {run.source} detected as {code}: "
        f"{[i18n.detect_language(t) for t in texts]}")

    words = i18n.compile_words([*i18n.heading_words("requirement", (code,)), *i18n.heading_words("responsibility", (code,)),
                                *i18n.marker_words("requirement", (code,))])
    assert any(words.search(text) for text in written), (
        f"none of the {code} language file's headings or requirement markers occur in {len(written)} saved {code} ads")
