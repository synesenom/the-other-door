"""Live smoke test per country: its country file still fits the places real ads name.

Opt-in (marked `live`): one request per country, page 1 of a board or discovery source serving it
(`probe`), from its largest city. The rows are `tests/live_matrix.COUNTRIES`; `scripts/smoke_report.py` lists each
country's result on the status page, apart from the sites'.
"""

import pytest

from door.matching import locality, prefilter, title_fit
from live_matrix import COUNTRIES, module


@pytest.mark.live
@pytest.mark.parametrize("cc", sorted(COUNTRIES))
def test_country_live(cc):
    run = COUNTRIES[cc]
    config = {"location": run.city, "search_keywords": [run.keyword], "role_targets": [run.keyword]}
    result = module(run).probe(config)
    assert result and result["structure_ok"], f"{run.source} gave no results page for {run.keyword!r} in {run.city}"
    places = [p["location"] for p in result["postings"] if p.get("location")]
    assert len(places) >= 5, f"only {len(places)} located ads from {run.source}: {places}"

    local = title_fit.name_pattern(locality.local_names(config))
    named = [place for place in places if local.search(title_fit.squash(place))]
    assert named, f"no ad names a place of the {cc} country file: {places[:10]}"

    foreign = [place for place in places if locality.location_is_non_local(place, config)]
    assert len(foreign) * 5 <= len(places), f"local ads taken for foreign ones: {foreign}"

    on_site = {"location": run.city, "remote": "no"}
    assert any(prefilter._is_location_compatible(place, on_site) for place in places), \
        f"an on-site profile in {run.city} keeps none of: {places[:10]}"
