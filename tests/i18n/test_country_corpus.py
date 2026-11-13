"""Each country file still fits the places real ads name (#19): page 1 of a board serving the country, from its
largest city, saved by `scripts/refresh_corpus.py` (`tests/i18n/corpus/countries/<cc>.json`). Offline: a site's
bad day never fails it; the site's own live test checks that it still answers."""

import pytest

from corpus_utils import load
from door.matching import locality, prefilter, title_fit
from live_matrix import COUNTRIES


@pytest.mark.parametrize("cc", sorted(COUNTRIES))
def test_the_country_file_fits_its_saved_ads(cc):
    run, saved = COUNTRIES[cc], load("countries", cc)
    assert (saved["source"], saved["city"]) == (run.source, run.city), "refresh the corpus: its row changed"
    config = {"location": run.city, "search_keywords": [run.keyword], "role_targets": [run.keyword]}
    places = saved["places"]
    assert len(places) >= 5, f"only {len(places)} located ads saved from {run.source}"

    local = title_fit.name_pattern(locality.local_names(config))
    named = [place for place in places if local.search(title_fit.squash(place))]
    assert named, f"no ad names a place of the {cc} country file: {places[:10]}"

    foreign = [place for place in places if locality.location_is_non_local(place, config)]
    assert len(foreign) * 5 <= len(places), f"local ads taken for foreign ones: {foreign}"

    on_site = {"location": run.city, "remote": "no"}
    assert any(prefilter._is_location_compatible(place, on_site) for place in places), \
        f"an on-site profile in {run.city} keeps none of: {places[:10]}"
