"""Live: `follow` finds H&M's, Telia's and Hilti's feeds from the names a Swedish board gives them (issue #566),
through Wikidata and their own careers sites. Opt-in (`./scripts/run-test.sh --live`)."""

import pytest

from door.commands import companies as companies_cmd
from door.core import ats_detect, wikidata
from live_utils import not_reached

pytestmark = pytest.mark.live

_LOCATION = "Stockholm"
_REAL_DNS = (companies_cmd._cname, companies_cmd._resolves)   # before the pipeline conftest turns DNS off


@pytest.fixture(autouse=True)
def _real_dns(monkeypatch):
    """H&M's careers host is found in DNS (`career.hm.com`)."""
    monkeypatch.setattr(companies_cmd, "_cname", _REAL_DNS[0])
    monkeypatch.setattr(companies_cmd, "_resolves", _REAL_DNS[1])


def _context():
    return companies_cmd.Context(
        places=tuple(ats_detect.places_for(_LOCATION)), hosts=companies_cmd._host_guesses(_LOCATION),
        site_labels=companies_cmd._site_labels(_LOCATION), employers=wikidata.Lookup(_LOCATION))


@pytest.mark.parametrize("name, website", [
    ("H & M Hennes & Mauritz GBC AB", "hm.com"),
    ("Telia Sverige AB", "telia.se"),
    ("Hilti Svenska Aktiebolag", "hilti."),
])
def test_wikidata_names_the_employers_website(name, website):
    found, note = wikidata.Lookup(_LOCATION).employer(companies_cmd._session(), name)
    if found is None and note and "Wikidata" in note and ("did not answer" in note or "stopped answering" in note):
        not_reached("wikidata", note)
    assert found is not None, note
    assert any(website in site for site in found.sites())


@pytest.mark.parametrize("name, platform", [
    ("H & M Hennes & Mauritz Sverige AB", "smartrecruiters"),
    ("Telia Sverige AB", "career_sites"),
    ("Hilti Svenska Aktiebolag", "career_sites"),
])
def test_a_large_swedish_employer_queued_by_name_is_followed_on_its_own_careers_site(name, platform):
    company = {"company": name, "links": [], "postings": 1, "titles": [], "sources": {"jobbsafari"}, "via": "jobbsafari"}

    found = companies_cmd._classify(companies_cmd._session(), company, set(), _context())

    assert found is not None and found[0] == "suggestions", found
    assert found[1]["platform"] == platform and found[1]["evidence"].startswith("Wikidata")
