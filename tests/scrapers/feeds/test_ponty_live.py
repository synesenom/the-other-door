"""Live smoke test for Ponty (#530): detect-only, so it checks the fact the look-through rests on.

Opt-in — run with:  ./scripts/run-test.sh --live

A current Ponty apply link (found through Platsbanken's JobSearch API) is recognised, and its logged-out form still
names the employer or links the customer's own site. A change in the form's markup is a reason to look again.
"""

import pytest
import requests

from door.scrapers.feeds import ponty
from door.scrapers.http_client import PoliteSession

_SEARCH = "https://jobsearch.api.jobtechdev.se/search"


def _current_apply_links() -> list[str]:
    hits = requests.get(_SEARCH, params={"q": "ponty-system", "limit": 100}, headers={"accept": "application/json"},
                        timeout=30).json().get("hits", [])
    links = [((h.get("application_details") or {}).get("url") or "").strip() for h in hits]
    return [link for link in links if "ponty-system.se" in link and "id=" in link]


@pytest.mark.live
def test_ponty_live_a_current_apply_form_still_names_an_employer():
    links = _current_apply_links()
    assert links, "Platsbanken no longer carries a Ponty apply link: find another source of current forms"
    session = PoliteSession(min_delay=1, max_delay=2, timeout=30, max_retries=1)

    named = []
    for link in links[:5]:
        det = ponty.detect_url(link)
        assert det.platform == "ponty" and det.entry is None and det.refusal == "cant_yet"
        out = ponty.resolve(session, det, link)
        if out.employer or out.site:
            named.append(out)
    assert named, "no Ponty apply form names an employer or links its site any more: the look-through needs a new route"
