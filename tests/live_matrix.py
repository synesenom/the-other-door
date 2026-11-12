"""The live smoke matrix past the per-site tests: one run per country and one per ad language.

Not a test module itself (no `test_` prefix). A site's own live test (`test_<site>_live.py`) proves
the site still answers; these prove each country's data and each language's data still fit real
ads, each on its own:

- a **country** run reads page 1 of ads (`probe`, one request) from a board or a discovery source
  serving the country, from its largest city, and checks the country file: the ads' locations name
  its places, are not taken for foreign ones (`locality`), and an on-site profile there keeps them
  (`prefilter`);
- a **language** run reads a few real ads written in it (with their descriptions) and checks the
  language file: the ads are detected as that language, and its headings and markers occur in them.

`tests/i18n/test_live_matrix_unit.py` fails until every country file and every language file has a
row here, every row's source serves its city, and every site and discovery source has a live test
or is listed in `NO_LIVE_TEST` with the reason.
"""

import importlib
from typing import NamedTuple


class Run(NamedTuple):
    city: str      # the profile's location
    source: str    # a board serving the city (`sites.boards_for_location`) or a discovery source for its country
    keyword: str   # a search with many ads there


def module(run: Run):
    """The run's scraper module, a site's or a discovery source's: both read ads with `probe` and `scrape`."""
    from door.core import discovery_sources, sites

    if run.source in sites.SITES:
        return importlib.import_module(sites.SITES[run.source].module)
    return discovery_sources.get(run.source)


def serves(run: Run) -> bool:
    """Whether the run's source reads ads for its city: a board of the city's country, or a discovery source
    registered for that country."""
    from door import i18n
    from door.core import discovery_sources, sites

    if run.source in sites.SITES:
        return run.source in sites.boards_for_location(run.city)
    country = i18n.country_for_location(run.city)
    countries = discovery_sources.get(run.source).COUNTRIES
    return not countries or (country is not None and country.code.lower() in countries)


# Country code -> a source of the country's ads and a keyword with plenty of them (Hungary has no board of its
# own: EURAXESS's Hungarian list).
COUNTRIES: dict[str, Run] = {
    "dk": Run("Copenhagen", "jobindex", "projektleder"),
    "hu": Run("Budapest", "euraxess", "research"),
    "fr": Run("Paris", "francetravail", "chef de projet"),
    "se": Run("Stockholm", "arbetsformedlingen", "project manager"),
    "gb": Run("London", "reed", "project manager"),
}

# Language code -> a source with ads written in it, and a keyword in that language.
LANGUAGES: dict[str, Run] = {
    "en": Run("Copenhagen", "thehub", "software engineer"),
    "da": Run("Copenhagen", "jobindex", "sygeplejerske"),
    "hu": Run("Budapest", "kozigallas", "ápoló"),
    "fr": Run("Paris", "francetravail", "comptable"),
    "sv": Run("Stockholm", "arbetsformedlingen", "projektledare"),
}

# Sites and discovery sources with no live test, and why. The status page lists them as such.
NO_LIVE_TEST: dict[str, str] = {}
