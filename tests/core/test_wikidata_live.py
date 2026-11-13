"""Live: an employer a board names only by its legal name is found on Wikidata and its website leads to its feed (#566, #19).

`wikidata.Lookup` still returns the employer's website for its name (mode ``lookup``), and `companies._by_website` (what `follow` asks
when no link or name probe found a feed) still finds its feed there (mode ``website``). The employers are
`live_employers.BY_NAME`. Opt-in (`./scripts/run-test.sh --live`).
"""

import pytest

from door.commands import companies as companies_cmd
from door.core import ats_detect, wikidata
from live_employers import BY_NAME
from live_utils import _page_refusal, fail, not_reached

pytestmark = pytest.mark.live

_IDS = [e.name for e in BY_NAME]


def _not_answering(note: str | None) -> bool:
    return bool(note) and "Wikidata" in note and ("did not answer" in note or "stopped answering" in note)


@pytest.mark.parametrize("employer", BY_NAME, ids=_IDS)
def test_wikidata_lookup_live(employer):
    found, note = wikidata.Lookup(employer.location).employer(companies_cmd._session(), employer.name)
    if found is None and _not_answering(note):
        not_reached("wikidata", note)
    assert found is not None, fail("wikidata", "lookup", f"{employer.name}: not found ({note})")
    assert any(employer.website in site for site in found.sites()), \
        fail("wikidata", "lookup", f"{employer.name}: {found.sites()} has no {employer.website}")


@pytest.mark.parametrize("employer", BY_NAME, ids=_IDS)
def test_wikidata_website_live(employer):
    ctx = companies_cmd.Context(
        places=tuple(ats_detect.places_for(employer.location)), hosts=companies_cmd._host_guesses(employer.location),
        site_labels=companies_cmd._site_labels(employer.location), employers=wikidata.Lookup(employer.location))
    notes: list[str] = []
    det = companies_cmd._by_website(companies_cmd._session(), employer.name, notes, ctx)
    if det is None and any(_not_answering(n) for n in notes):
        not_reached("wikidata", "; ".join(notes))
    if det is None and (why := _page_refusal(employer.careers)) is not None:
        not_reached("wikidata", f"{employer.name}: {why}")
    assert det is not None and det.platform == employer.platform and det.entry, \
        fail("wikidata", "website", f"{employer.name}: {det} ({'; '.join(notes)})")
    assert det.evidence.startswith("Wikidata"), fail("wikidata", "website", f"{employer.name}: {det.evidence}")
