"""Live smoke test for the Phenom look-through (#438): Genmab's career host, a Phenom front end for Workday.

Opt-in — run with:  ./scripts/run-test.sh --live

Whether Genmab's Workday site lists jobs publicly is up to Genmab (it listed none when this was written), so the
test asks only that the look-through finds the Workday site behind the front end and gives a verdict.
"""

import pytest

from door.scrapers.feeds import phenom
from door.scrapers.http_client import PoliteSession


@pytest.mark.live
def test_phenom_live_finds_the_workday_site_behind_the_front_end():
    session = PoliteSession(min_delay=1, max_delay=2, timeout=30, max_retries=1)
    det = phenom.detect_cname("careers.genmab.com", "genmab.phenompeople.net", "careers.genmab.com is a CNAME for genmab.phenompeople.net")

    out = phenom.resolve(session, det, "https://careers.genmab.com/")

    assert "genmab.wd3.myworkdayjobs.com" in out.evidence
    assert out.entry is not None or out.refusal == "cant_yet"
