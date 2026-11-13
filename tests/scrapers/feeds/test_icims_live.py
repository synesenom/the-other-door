"""Live smoke test for iCIMS: detect-only, so it checks that a real employer's careers page is still
recognised as one (#19). Opt-in: run with `./scripts/run-test.sh --live`.
"""

import pytest

from live_utils import assert_detects


@pytest.mark.live
def test_icims_detection_live():
    """A real employer's careers page still shows icims and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("icims")
