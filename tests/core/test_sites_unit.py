"""The site registry (`door.core.sites`): one entry drives scraping and validation."""

import pytest

import importlib.util

from door import i18n
from door.core import sites
from door.core.sites import SITES


def test_each_site_lists_the_countries_it_serves_by_iso_code():
    assert SITES["jobindex"].countries == ("dk",)
    assert SITES["thehub"].countries == ("dk",)
    assert SITES["workable"].countries == ()  # any country


def test_every_country_a_site_serves_has_a_country_file():
    """A country is supported when `i18n/country/<cc>.toml` gives its words and places."""
    for site in SITES.values():
        for code in site.countries:
            assert code in i18n.countries(), f"{site.name} serves {code!r}, which has no country file"


def test_a_sites_module_is_named_after_it_in_the_folder_of_its_kind():
    """Keyword boards in scrapers/boards/, employer feed platforms (a board with a feed, Workable, too) in
    scrapers/feeds/; discovery sources are not sites (scrapers/discovery/, `discovery_sources.SOURCES`)."""
    assert SITES["jobindex"].module == "door.scrapers.boards.jobindex"
    assert SITES["thehub"].module == "door.scrapers.boards.thehub"
    assert SITES["workable"].module == "door.scrapers.feeds.workable"
    assert SITES["greenhouse"].module == "door.scrapers.feeds.greenhouse"
    for site in SITES.values():
        assert importlib.util.find_spec(site.module) is not None, f"{site.name}: no module {site.module}"


_FEED_KEYS = {
    "greenhouse": "greenhouse_boards", "lever": "lever_companies", "workable": "workable_companies",
    "ashby": "ashby_companies", "recruitee": "recruitee_companies", "pinpoint": "pinpoint_companies",
    "smartrecruiters": "smartrecruiters_companies", "signatur": "signatur_companies",
    "dayforce": "dayforce_companies", "reachmee": "reachmee_companies", "emply": "emply_tenants", "oracle_hcm": "oracle_hcm_companies", "teamtailor": "teamtailor_companies", "jobylon": "jobylon_companies",
    "successfactors": "successfactors_companies", "hr_manager": "hr_manager_aliases", "career_sites": "career_sites", "recman": "recman_companies", "varbi": "varbi_tenants",
    "personio": "personio_companies", "talentsoft": "talentsoft_hosts", "taleez": "taleez_companies",
    "flatchr": "flatchr_companies",
    "jobtrain": "jobtrain_companies",
    "networx": "networx_companies",
    "beetween": "beetween_companies",
    "digitalrecruiters": "digitalrecruiters_sites",
    "visma_recruit": "visma_recruit_companies",
    "eploy": "eploy_hosts",
}


def test_the_feed_sites_are_the_platforms_with_the_keys_the_scrapers_read():
    from door.core import sites

    assert sites.FEED_SITES == _FEED_KEYS
    assert {name: site.config_key for name, site in SITES.items() if site.config_key} == _FEED_KEYS


def test_a_detection_takes_its_config_key_from_the_registry():
    from door.core import ats_detect

    assert ats_detect.Detection("lever", "x", "").config_key == "lever_companies"
    assert ats_detect.Detection("lever", None, "").config_key is None
    assert ats_detect.Detection("phenom", "x", "").config_key is None


def test_sites_for_a_country_are_its_own_plus_the_worldwide_ones():
    from door.core.sites import sites_for_country

    danish = sites_for_country("dk")
    assert {"jobindex", "thehub", "jobbank", "workable"} <= set(danish)
    swedish = sites_for_country("se")
    assert "jobindex" not in swedish and "thehub" not in swedish and "workable" in swedish


def test_sites_for_an_unknown_country_are_the_worldwide_ones():
    from door.core.sites import sites_for_country

    assert set(sites_for_country("de")) == {n for n, s in SITES.items() if not s.countries}


def test_sites_without_a_country_are_the_worldwide_ones():
    from door.core.sites import sites_for_country

    assert sites_for_country(None) == sites_for_country("de")


def test_every_site_links_the_terms_it_was_checked_against():
    """Issue #226: a site is added only after its terms are read."""
    for site in SITES.values():
        assert site.terms_url.startswith("https://"), site.name


def test_every_site_has_a_verdict_and_a_terms_summary():
    from door.core.sites import VERDICTS

    for site in SITES.values():
        assert site.verdict in VERDICTS, site.name
        assert site.terms_summary and "\n" not in site.terms_summary, site.name


def test_no_site_is_unsure_without_its_own_switch():
    unsure = [s.name for s in SITES.values() if s.verdict == "unsure"]
    assert not unsure, (
        f"{unsure[0]} is unsure: an unsure source needs its own switch and the disclaimer before it can be "
        "added (#569); see docs/job-sites.md, How The other door fetches"
    )


@pytest.mark.parametrize("name", list(SITES))
def test_every_site_module_has_a_terms_passage(name):
    import importlib
    import re

    doc = importlib.import_module(SITES[name].module).__doc__ or ""
    assert re.search(r"(?m)^\s*Terms\b", doc), (
        f"{name}: its module docstring needs a line starting 'Terms' quoting the terms its verdict rests on, "
        "or saying no terms were found (docs/job-sites.md, How The other door fetches)"
    )


def test_terms_url_is_required():
    import pytest

    from door.core.sites import Site

    with pytest.raises(TypeError):
        Site("nowhere")  # type: ignore[call-arg]


def test_an_unknown_verdict_is_refused():
    from door.core.sites import Site

    with pytest.raises(ValueError):
        Site("nowhere", label="N", terms_url="https://example.com", verdict="maybe", terms_summary="x")


def test_the_boards_are_the_sites_that_search_by_keyword():
    """jobindex, thehub, euraxess (researcher jobs), globalnyt, jobbank, reed, jobs_ac_uk, nhs_jobs, jobmaskinen, arbetsformedlingen (Platsbanken), francetravail, choisirleservicepublic, kozigallas, workable's cross-company search and reliefweb; the per-company feeds are not boards."""
    from door.core.sites import BOARDS

    assert BOARDS == ["jobindex", "thehub", "euraxess", "globalnyt", "jobbank", "reed", "jobs_ac_uk", "nhs_jobs", "jobmaskinen", "arbetsformedlingen", "francetravail", "choisirleservicepublic", "kozigallas", "workable", "reliefweb"]


def test_workable_is_both_a_board_and_a_feed():
    assert SITES["workable"].board and SITES["workable"].config_key == "workable_companies"


def test_boards_for_a_country_are_the_boards_serving_it():
    from door.core.sites import boards_for_country

    assert boards_for_country("dk") == ["jobindex", "thehub", "euraxess", "globalnyt", "jobbank", "jobmaskinen", "workable", "reliefweb"]
    assert boards_for_country("hu") == ["euraxess", "kozigallas", "workable", "reliefweb"]
    assert boards_for_country("fr") == ["euraxess", "francetravail", "choisirleservicepublic", "workable", "reliefweb"]
    assert boards_for_country("se") == ["euraxess", "arbetsformedlingen", "workable", "reliefweb"]


def test_boards_for_a_location_are_the_boards_of_its_country(country_boards):
    from door.core import sites

    assert sites.boards_for_location("Copenhagen, Denmark") == ["jobindex", "thehub", "euraxess", "globalnyt", "jobbank", "jobmaskinen", "workable", "reliefweb"]
    assert sites.boards_for_location("Aarhus") == ["jobindex", "thehub", "euraxess", "globalnyt", "jobbank", "jobmaskinen", "workable", "reliefweb"]
    assert sites.boards_for_location("Berlin, Germany") == ["workable", "reliefweb"]  # no country file: the worldwide boards
    assert sites.boards_for_location("") == ["workable", "reliefweb"]


def test_every_site_has_a_readable_name():
    for name, site in sites.SITES.items():
        assert site.label.strip(), name


def test_source_name_reads_a_site_and_the_sources_that_are_not_sites():
    assert sites.source_name("jobindex") == "Jobindex"
    assert sites.source_name("successfactors") == "SuccessFactors"
    assert sites.source_name("career_sites") == "the employer's site"
    assert sites.source_name("linkedin") == "LinkedIn"
    # Added by hand, or an unknown value: nothing worth a "via".
    assert sites.source_name("manual") is None
    assert sites.source_name("nonesuch") is None
    assert sites.source_name(None) is None


def test_the_development_boards_are_registered():
    assert SITES["reliefweb"].board and SITES["reliefweb"].countries == ()
    assert SITES["globalnyt"].board and SITES["globalnyt"].countries == ("dk",)
    assert SITES["reliefweb"].module == "door.scrapers.boards.reliefweb"
    assert SITES["globalnyt"].module == "door.scrapers.boards.globalnyt"
