"""The rows (`tests/live_matrix.py`) cover every dimension, so each can fail on its own:
every country file and every language file (every site and discovery source: `tests/scrapers/test_live_modes_unit.py`)."""

from door import i18n
from live_matrix import COUNTRIES, LANGUAGES, serves


def test_every_country_file_has_a_row():
    assert set(COUNTRIES) == set(i18n.countries())


def test_every_language_file_has_a_row():
    assert set(LANGUAGES) == set(i18n.languages())


def test_a_country_run_reads_ads_of_that_country(country_boards):
    for cc, run in COUNTRIES.items():
        country = i18n.country_for_location(run.city)
        assert country is not None and country.code.lower() == cc, f"{run.city} is not in {cc}"
        assert serves(run), f"{run.source} does not serve {run.city}"


def test_a_language_run_reads_a_source_serving_its_city(country_boards):
    for code, run in LANGUAGES.items():
        assert serves(run), f"{code}: {run.source} does not serve {run.city}"


