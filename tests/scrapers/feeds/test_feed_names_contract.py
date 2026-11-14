"""What every single-employer feed does with its entries, one contract over the feeds, each served
from its own saved fixture by the helpers of its scrape test:

- issue #291: `collect` hands the scraper the followed employers' names (`_names`), and every posting
  of an entry carries its followed name; without one, the feed's own guess stays;
- an entry that cannot be read is a recorded error, and the entries after it are still read."""

import importlib.util
import sys

import pytest
import responses

from door.core import companies
from door.core.sites import SITES
from door.scrapers import drain_errors
from paths import TESTS_DIR

_HERE = TESTS_DIR / "scrapers" / "feeds"


def _helpers(stem):
    """The module of `feeds/<stem>.py`, loaded once for its serve helpers and constants."""
    name = f"_feed_helpers_{stem}"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, _HERE / f"{stem}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def _get(url_attr, body):
    return lambda m: responses.add(responses.GET, getattr(m, url_attr), body=body(m))


# site: (its scrape test module, how to serve one entry, the entry as written, the feed's own name for it)
_CASES = {
    "ashby": ("test_ashby_scrape", _get("_BOARD", lambda m: m._fx()), "https://jobs.ashbyhq.com/Pleo", "pleo"),
    "beetween": ("test_beetween_scrape", lambda m: (m._add_list(), m._add_ads()), "giboire", None),
    "dayforce": ("test_dayforce_scrape", lambda m: m._mock(), "natus/CANDIDATEPORTALSENSORY", "Natus"),
    "digitalrecruiters": ("test_digitalrecruiters_scrape", lambda m: m._serve_monoprix(),
                          "https://recrutement.monoprix.fr/fr/annonces", None),
    "emply": ("test_emply_scrape", lambda m: responses.add(responses.POST, m._API, json=m._fx()), "dca", None),
    "eploy": ("test_eploy_scrape", lambda m: m._serve(), "https://vitalityweb.eploy.net/vacancies/", None),
    "flatchr": ("test_flatchr_scrape", _get("_FEED", lambda m: m._fx()), "flatchr", None),
    "greenhouse": ("test_greenhouse_scrape", _get("_JOBS_URL", lambda m: m._fx("jobs_page.json")),
                   "https://boards.greenhouse.io/acme", "Greenhouse"),
    "jobtrain": ("test_jobtrain_scrape", lambda m: m._mock_crisis(), "jobs.crisis.org.uk", None),
    "jobylon": ("test_jobylon_scrape", lambda m: m._mock_lyko(), "2420", None),
    "lever": ("test_lever_scrape", _get("_POSTINGS_URL", lambda m: m._fx("postings.json")), "Acme", "acme"),
    "networx": ("test_networx_scrape", lambda m: m._mock_all(), "3509", None),
    "personio": ("test_personio_scrape", _get("_XML", lambda m: m._read()), "pno-group-europe", None),
    "pinpoint": ("test_pinpoint_scrape", _get("_FEED", lambda m: m._fx()), "factbird", "Factbird"),
    "reachmee": ("test_reachmee_scrape", lambda m: m._mock_sv(), "I003/354/5", None),
    "recman": ("test_recman_scrape", lambda m: m._mock_all(), "pn", None),
    "recruitee": ("test_recruitee_scrape", _get("_OFFERS", lambda m: m._fx()), "https://Famly.recruitee.com/", "Famly"),
    "signatur": ("test_signatur_scrape", lambda m: m._mock_all(), "2296", "Helsingør Kommune"),
    "smartrecruiters": ("test_smartrecruiters_scrape", lambda m: m._mock_all(),
                        "https://jobs.smartrecruiters.com/interikeagroup/", "Inter IKEA Group"),
    "successfactors": ("test_successfactors_scrape",
                       lambda m: (m._allow_robots(), responses.add(responses.GET, m._FEED_URL, body=m._fx("feed_sample.xml"))),
                       "careers.novonordisk.com", "Novo Nordisk"),
    "taleez": ("test_taleez_scrape", lambda m: m._mock_all(), "donecle", None),
    "talentsoft": ("test_talentsoft_scrape", lambda m: m._serve(), "agrica-career.talent-soft.com", None),
    "teamtailor": ("test_teamtailor_scrape", _get("_JOBS_URL", lambda m: m._fx("jobs_page.json")), "Acme", None),
    "varbi": ("test_varbi_scrape", lambda m: m._serve_ki(), "ki", None),
    "visma_recruit": ("test_visma_recruit_scrape", lambda m: m._serve_nassjo(), "f636d73d-8356-43c6-99bd-ba01addf1b55", None),
    "workable": ("test_workable_scrape", _get("_WIDGET", lambda m: m._widget()), "https://apply.workable.com/Dreamdata/", None),
}
# An entry nothing answers for, in each platform's own form.
_UNREACHABLE = {
    "ashby": "nope", "beetween": "nope", "dayforce": "nope/nope", "digitalrecruiters": "recrutement.nope.fr",
    "emply": "nope", "eploy": "nope.eploy.net", "flatchr": "nope", "greenhouse": "nope", "jobtrain": "jobs.nope.org.uk",
    "jobylon": "9999999", "lever": "nope", "networx": "9999", "personio": "nope", "pinpoint": "nope",
    "reachmee": "I999/999/9", "recman": "nope", "recruitee": "nope", "signatur": "9999", "smartrecruiters": "nope",
    "successfactors": "careers.nope.com", "taleez": "nope", "talentsoft": "nope.talent-soft.com", "teamtailor": "nope",
    "varbi": "nope", "visma_recruit": "00000000-0000-0000-0000-000000000000", "workable": "nope",
}
# Covered in their own tests: a multi-employer portal keeps each posting's own employer (hr_manager);
# career_sites' entries are whole sites and listings (test_career_sites_listing_scrape.py);
# oracle_hcm's mapping test runs with a name map.
_OWN_TESTS = {"hr_manager", "career_sites", "oracle_hcm"}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


def test_every_feed_platform_is_checked():
    feeds = {name for name, site in SITES.items() if site.config_key}
    assert set(_CASES) | _OWN_TESTS == feeds and set(_UNREACHABLE) == set(_CASES)


def _scrape(site, names, before=()):
    stem, serve, entry, _ = _CASES[site]
    key = SITES[site].config_key
    config = {key: [*before, entry]}
    if names:
        config["_names"] = {key: {companies.entry_key(entry): "Followed Employer"}}
    serve(_helpers(stem))
    return importlib.import_module(SITES[site].module).scrape(config)


@pytest.mark.parametrize("site", sorted(_CASES))
@responses.activate
def test_the_followed_name_labels_every_posting(site):
    postings = _scrape(site, names=True)

    assert postings and {p["company"] for p in postings} == {"Followed Employer"}
    assert all(p["id"].startswith(f"{site}.") for p in postings)


@pytest.mark.parametrize("site", sorted(s for s, case in _CASES.items() if case[3]))
@responses.activate
def test_without_a_name_map_the_feeds_own_name_stays(site):
    assert {p["company"] for p in _scrape(site, names=False)} == {_CASES[site][3]}


@pytest.mark.parametrize("site", sorted(_CASES))
@responses.activate
def test_an_entry_that_cannot_be_read_is_a_recorded_error_and_the_next_is_read(site):
    alone = len(_scrape(site, names=False))
    responses.reset()
    drain_errors()

    postings = _scrape(site, names=False, before=[_UNREACHABLE[site]])

    assert alone and len(postings) == alone
    assert drain_errors().get(site)
