"""The rows past the per-site tests: one per country and one per ad language, and the sites without a live test.

Not a test module itself (no `test_` prefix). A site's own live test (`test_<site>_live.py`) proves
the site still answers; `scripts/refresh_corpus.py` saves each row's real ads in `tests/i18n/corpus/`, and
the offline checks (`tests/i18n/test_country_corpus.py`, `test_language_corpus.py`) prove each country's
data and each language's data still fit them, each on its own:

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


# Country code -> a source of the country's ads and a keyword with plenty of them.
COUNTRIES: dict[str, Run] = {
    "dk": Run("Copenhagen", "jobindex", "projektleder"),
    "hu": Run("Budapest", "kozigallas", "ápoló"),
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

# Each board's saved zero-hit answer (a real one, path relative to `tests/scrapers`): the answer a quiet day
# gives, which the scraper must read as an answer (`record_answered`), never as a changed site (#19).
ZERO_HIT_FIXTURES: dict[str, str] = {
    "jobindex": "boards/fixtures/jobindex/search_empty.html",
    "thehub": "boards/fixtures/thehub/listing_empty_real.html",
    "globalnyt": "boards/fixtures/globalnyt/stilling_list_empty.json",
    "jobbank": "boards/fixtures/jobbank/search_empty.html",
    "reed": "boards/fixtures/reed/search_empty.html",
    "jobs_ac_uk": "boards/fixtures/jobs_ac_uk/search_empty.html",
    "nhs_jobs": "boards/fixtures/nhs_jobs/search_empty.html",
    "jobmaskinen": "boards/fixtures/jobmaskinen/search_no_results.html",
    "arbetsformedlingen": "boards/fixtures/arbetsformedlingen/empty.json",
    "francetravail": "boards/fixtures/francetravail/search_empty.html",
    "choisirleservicepublic": "boards/fixtures/choisirleservicepublic/search_empty.html",
    "kozigallas": "boards/fixtures/kozigallas/list_empty.html",
    "workable": "feeds/fixtures/workable/search_empty.json",
    "reliefweb": "boards/fixtures/reliefweb/empty.xml",
}

# Boards with no zero-hit check, and why.
NO_ZERO_HIT: dict[str, str] = {
    "euraxess": "no keyword search: it reads the country's whole list, so no keyword can come back empty",
}


# What each site's live postings may lack against the field contract (`live_utils.assert_field_contract`, #19). A site
# not listed meets the defaults. Keys (all optional):
#   company_share            share of postings that must name an employer other than the site (default 0.9)
#   description_share        share with a description of at least `description_min` characters (default 0.9; 0 = not
#                            required, only the boilerplate rule still reads those that have one)
#   description_min          shortest description counted (default 80)
#   location                 False: skip the "not another country's" rule of a country board
#   location_share           the share of local postings needed (default 0.9)
#   posted_at_future_days    how far ahead a date may be (default 1)
# "unverified: tune after a live run" marks a waiver no live run has confirmed; tighten it once one has.
FIELD_EXCEPTIONS: dict[str, dict] = {
    "jobbank": {"location_share": 0.5},                                # a Danish search also lists "Udlandet (øvrige)" (abroad) ads
    "euraxess": {"location": False},                                   # the location is "<city>, <country>"; its live test checks the country
    "kozigallas": {"posted_at_future_days": 14},
    "hr_manager": {"description_share": 0.8},                         # the newest ads may have no text yet (RegionH, 2026-11-13: 3 of 100, 2 of the first 10)                       # the date can be a planned publication date
}
