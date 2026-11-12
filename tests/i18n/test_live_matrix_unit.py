"""The live smoke matrix (`tests/live_matrix.py`) covers every dimension, so each can fail on its own:
every country file, every language file, every site and every discovery source."""

from door import i18n
from door.core import discovery_sources, sites
from live_matrix import COUNTRIES, LANGUAGES, NO_LIVE_TEST, serves
from paths import TESTS_DIR


def test_every_country_file_has_a_live_run():
    assert set(COUNTRIES) == set(i18n.countries())


def test_every_language_file_has_a_live_run():
    assert set(LANGUAGES) == set(i18n.languages())


def test_a_country_run_reads_ads_of_that_country(country_boards):
    for cc, run in COUNTRIES.items():
        country = i18n.country_for_location(run.city)
        assert country is not None and country.code.lower() == cc, f"{run.city} is not in {cc}"
        assert serves(run), f"{run.source} does not serve {run.city}"


def test_a_language_run_reads_a_source_serving_its_city(country_boards):
    for code, run in LANGUAGES.items():
        assert serves(run), f"{code}: {run.source} does not serve {run.city}"


def test_every_site_and_discovery_source_has_a_live_test_or_a_reason():
    names = {*sites.SITES, *discovery_sources.SOURCES}
    with_test = {p.stem[len("test_"):-len("_live")] for p in (TESTS_DIR / "scrapers").rglob("test_*_live.py")}
    assert names - with_test - set(NO_LIVE_TEST) == set()
    assert set(NO_LIVE_TEST) <= names and not set(NO_LIVE_TEST) & with_test
