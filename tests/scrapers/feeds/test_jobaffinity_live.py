"""Live smoke test for Jobaffinity (#563): detect-only, so it checks the fact the look-through rests on.

Opt-in — run with:  ./scripts/run-test.sh --live

The recorded apply form's logged-out page is still served and still names its data controller as the employer.
A change in the notice's wording is a reason to look again.
"""

import pytest

from door.scrapers.feeds import jobaffinity
from door.scrapers.http_client import PoliteSession
from live_utils import assert_detects

_URL = "https://jobaffinity.fr/apply/wqrlmvgzpyc67d0izf"


@pytest.mark.live
def test_jobaffinity_live_an_apply_form_still_names_an_employer():
    session = PoliteSession(min_delay=1, max_delay=2, timeout=30, max_retries=1)
    det = jobaffinity.detect_url(_URL)
    assert det.platform == "jobaffinity" and det.entry is None and det.refusal == "cant_yet"
    out = jobaffinity.resolve(session, det, _URL)
    assert out.employer, "the apply form no longer names its data controller (or the ad was withdrawn): look again"


@pytest.mark.live
def test_jobaffinity_detection_live():
    """A real employer's careers page still shows jobaffinity and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("jobaffinity")
