"""iCIMS career portals are recognised but not followed (issue #603): the vendor's terms ban automated access to
``icims.com`` and its subdomains, which is where every hosted portal lives."""

import pytest

from door.core import ats_detect
from door.scrapers.sdk import Detection
from door.scrapers.feeds import icims
from door.scrapers.http_client import PoliteSession


@pytest.mark.parametrize("url", [
    "https://careers-sisk.icims.com/jobs/3203/site-manager--/job?in_iframe=1",
    "https://careers-linesight.icims.com/jobs/search?ss=1&in_iframe=1",
    "https://uscareers-pepsico.icims.com/jobs/search?ss=1",
    "https://unitedstates-aon.icims.com/jobs/search",
    "http://sisk.icims.com/",
])
def test_a_portal_link_is_named_but_not_followed(url):
    det = icims.detect_url(url)
    assert det.platform == "icims" and det.entry is None
    assert det.refusal == "must_not" and "iCIMS" in det.evidence and "terms" in det.evidence


@pytest.mark.parametrize("url", [
    "https://www.icims.com/", "https://icims.com/", "https://community.icims.com/", "https://social.icims.com/legal/terms",
    "https://cdn02.icims.com/platform_1/css/icims.css", "https://developer-community.icims.com/", "https://marketplace.icims.com/",
    "https://provider-eu.icims.com/x", "https://icims.help/candidate-faq", "https://acme.com/?u=icims.com",
    "https://notificims.com/", "https://a.b.icims.com/",
])
def test_the_vendors_own_hosts_and_other_domains_are_not_portals(url):
    assert icims.detect_url(url) is None


def test_a_career_host_that_is_a_cname_for_a_portal_stays_a_career_site():
    """The employer's own domain is not an icims.com host: `career_sites` reads its markup as before."""
    assert not hasattr(icims, "detect_cname")
    assert ats_detect.from_cname("careers.veo.co", "veo.icims.com").platform == "career_sites"


def test_a_link_to_a_portal_does_not_decide_which_platform_a_page_is_on():
    assert icims.LINK_PLATFORMS == ()
    assert not hasattr(icims, "scrape")


@pytest.mark.parametrize("url, name", [
    ("https://careers-sisk.icims.com/jobs/3203/site-manager--/job", "Sisk"),
    ("https://uscareers-pepsico.icims.com/jobs/search", "Pepsico"),
    ("https://unitedstates-aon.icims.com/jobs/search", "Aon"),
    ("https://careers-john-sisk.icims.com/", "John Sisk"),
    ("https://linesight.icims.com/", "Linesight"),
    ("https://jobs-acme-corp.icims.com/", "Acme Corp"),
])
def test_the_employer_is_named_by_the_portal_host(url, name):
    assert icims.employer_name(url) == name


@pytest.mark.parametrize("url", ["https://www.icims.com/", "https://careers.icims.com/", "https://jobs.icims.com/", "https://acme.com/x"])
def test_a_host_that_names_no_employer_gives_no_name(url):
    assert icims.employer_name(url) is None


class _NoNetwork(PoliteSession):
    def get(self, *args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("iCIMS hosts are never requested")


def test_resolve_names_the_employer_for_follow_without_a_request():
    url = "https://careers-sisk.icims.com/jobs/3203/site-manager--/job"
    det = icims.detect_url(url)

    out = icims.resolve(_NoNetwork(), det, url)

    assert out.platform == "icims" and out.entry is None and out.refusal == "must_not"
    assert out.employer == "Sisk" and out.site is None


def test_resolve_leaves_a_detection_that_names_no_employer_alone():
    det = Detection("icims", None, "x: not followed", "must_not")

    assert icims.resolve(_NoNetwork(), det, "https://www.icims.com/") == det


def test_the_dispatcher_finds_a_portal_by_its_link():
    assert ats_detect.from_url("https://careers-sisk.icims.com/jobs/search").platform == "icims"
    assert "icims.com" in ats_detect.platform_domains()
