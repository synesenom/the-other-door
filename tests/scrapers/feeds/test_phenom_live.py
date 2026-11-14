"""Live smoke tests for the Phenom look-through (#438), one per mode (#19): Genmab's career host, a Phenom front end
for Workday.

Opt-in — run with:  ./scripts/run-test.sh --live

Whether Genmab's Workday site lists jobs publicly is up to Genmab (it listed none when this was written), so the
look-through test asks only that it finds the Workday site behind the front end and gives a verdict.
"""

import pytest

from door.scrapers.feeds import phenom
from door.scrapers.http_client import PoliteSession
from live_utils import assert_detects


@pytest.mark.live
def test_phenom_lookthrough_live():
    """The look-through still finds the Workday site behind Genmab's Phenom front end."""
    session = PoliteSession(min_delay=1, max_delay=2, timeout=30, max_retries=1)
    det = phenom.detect_cname("careers.genmab.com", "genmab.phenompeople.net", "careers.genmab.com is a CNAME for genmab.phenompeople.net")

    out = phenom.resolve(session, det, "https://careers.genmab.com/")

    assert "genmab.wd3.myworkdayjobs.com" in out.evidence
    assert out.entry is not None or out.refusal == "cant_yet"


@pytest.mark.live
def test_phenom_detection_live():
    """A real employer's careers page still shows phenom and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("phenom")
