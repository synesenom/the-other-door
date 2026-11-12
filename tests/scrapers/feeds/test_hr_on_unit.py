"""HR-ON links and pages are recognised but not followed (issue #282)."""

import pytest

from door.scrapers.feeds import hr_on


@pytest.mark.parametrize("url", [
    "https://www.dalux.com/careers/job?hr=show-job/327277&locale=en_US", "https://bankinvest.hr-on.com/show-job/357305?linkref=1",
])
def test_an_hr_on_link_is_named_but_not_followed(url):
    det = hr_on.detect_url(url)
    assert det.platform == "hr_on" and det.entry is None and "HR-ON" in det.evidence


def test_a_page_that_embeds_the_hr_on_frame_is_an_hr_on_site():
    html = '<script src="https://recruit.hr-on.com/frame-api/customers/dalux.js?"></script>'
    det = hr_on.detect_html(html, "https://www.dalux.com/careers/")
    assert det.platform == "hr_on" and det.entry is None
    assert hr_on.detect_html("<p>x</p>", "https://www.dalux.com/") is None
    assert hr_on.detect_url("https://acme.dk/careers") is None


def test_a_link_to_hr_on_does_not_decide_which_platform_a_page_is_on():
    assert hr_on.LINK_PLATFORMS == ()
