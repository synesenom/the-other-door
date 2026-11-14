"""What every site does when the network fails it (#178): `scrape` records the error and returns,
never raises, and `probe` says whether the site was unreachable or walled. One contract over the
registry instead of a copy per site; the sites' own parsing stays in their tests."""

import importlib
import re

import pytest
import responses

from door.core.sites import ALL_SITES, FEED_SITES, SITES
from door.scrapers import drain_errors, drain_pushback

# One entry per feed platform, as a user's profile would hold it.
_ENTRY = {
    "ashby": "pleo", "beetween": "giboire", "career_sites": "https://careers.acme.dk",
    "dayforce": "natus/candidateportalsensory", "digitalrecruiters": "recrutement.monoprix.fr",
    "emply": "dca", "eploy": "vitalityweb.eploy.net", "flatchr": "flatchr", "greenhouse": "acme",
    "hr_manager": "kkdk", "jobtrain": "jobs.crisis.org.uk", "jobylon": "2420", "lever": "acme",
    "networx": "3509", "oracle_hcm": "efzu.fa.em2.oraclecloud.com/CX_1", "personio": "pno-group-europe",
    "pinpoint": "factbird", "reachmee": "I003/354/5", "recman": "pn", "recruitee": "famly",
    "signatur": "2296", "smartrecruiters": "interikeagroup", "successfactors": "career2.successfactors.eu",
    "taleez": "donecle", "talentsoft": "agrica-career.talent-soft.com", "teamtailor": "acme",
    "varbi": "ki", "visma_recruit": "f636d73d-8356-43c6-99bd-ba01addf1b55", "workable": "dreamdata",
}
# career_sites crawls an employer's own site: a host that answers nothing is a site with nothing
# to read (its own tests pin that), not a failure.
_FETCHING = [s for s in ALL_SITES if s != "career_sites"]
# A board that reads its whole list without keywords probes without them too.
_PROBES_WITHOUT_CONFIG = {"euraxess"}
# Boards that read one list whole and filter it, so no request names a keyword.
_READS_THE_WHOLE_LIST = {"euraxess", "globalnyt"}
_CITY = {"dk": "Copenhagen", "gb": "London", "se": "Stockholm", "fr": "Paris", "hu": "Budapest"}


def _config(site):
    s = SITES[site]
    if site in FEED_SITES:
        return {s.config_key: [_ENTRY[site]]}
    return {"search_keywords": ["project manager"], "location": _CITY[s.countries[0]] if s.countries else "Copenhagen"}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


def test_every_feed_platform_has_an_entry_here():
    assert set(_ENTRY) == set(FEED_SITES)


@pytest.mark.parametrize("site", sorted(FEED_SITES))
def test_a_feed_with_no_entries_returns_nothing(site):
    with responses.RequestsMock():   # any request would raise
        assert importlib.import_module(SITES[site].module).scrape({}) == []


@pytest.mark.parametrize("site", sorted(set(ALL_SITES) - _PROBES_WITHOUT_CONFIG))
def test_without_entries_or_keywords_probe_is_none(site):
    assert importlib.import_module(SITES[site].module).probe({"location": "Copenhagen"}) is None


@pytest.mark.parametrize("site", _FETCHING)
def test_a_connection_error_is_recorded_not_raised(site):
    drain_errors()
    drain_pushback(site)
    with responses.RequestsMock(assert_all_requests_are_fired=False):   # nothing served: every request fails
        assert importlib.import_module(SITES[site].module).scrape(_config(site)) == []
    errors = drain_errors().get(site)
    assert errors, f"{site} swallowed a connection error without recording it"
    assert drain_pushback(site) is False   # a network failure is no refusal: the site does not rest
    if site not in FEED_SITES and site not in _READS_THE_WHOLE_LIST:
        assert any("project manager" in e for e in errors)   # the error names the keyword it was searching


@pytest.mark.parametrize("site", _FETCHING)
def test_probe_on_a_connection_error_is_unreachable(site):
    drain_errors()
    with responses.RequestsMock(assert_all_requests_are_fired=False):
        result = importlib.import_module(SITES[site].module).probe(_config(site))
    assert result["structure_ok"] is False and result.get("unreachable") is True
    assert drain_errors() == {}   # a probe reports, it leaves no run errors behind


@pytest.mark.parametrize("status", [401, 403, 429])
@pytest.mark.parametrize("site", _FETCHING)
def test_probe_on_a_refusal_is_a_wall(site, status):
    drain_errors()
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        for method in (responses.GET, responses.POST):
            mock.add(method, re.compile(r".*"), status=status, body="no")
        result = importlib.import_module(SITES[site].module).probe(_config(site))
    assert result["structure_ok"] is False and result.get("wall") is True
    assert drain_errors() == {}


@pytest.mark.parametrize("site", _FETCHING)
def test_a_server_error_is_recorded_and_is_no_refusal(site):
    drain_errors()
    drain_pushback(site)
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        for method in (responses.GET, responses.POST):
            mock.add(method, re.compile(r".*"), status=500, body="boom")
        assert importlib.import_module(SITES[site].module).scrape(_config(site)) == []
    assert drain_errors().get(site)
    assert drain_pushback(site) is False
