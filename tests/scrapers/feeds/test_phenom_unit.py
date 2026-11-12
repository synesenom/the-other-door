"""Phenom (issue #282, #438): a career host that is a CNAME for Phenom's is looked through to the system behind
it, followed only when that system's public job list is not empty."""

import pytest
import responses

from door.scrapers.feeds import phenom
from door.scrapers.http_client import PoliteSession
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "phenom"
_HOST = "careers.acmepharma.example"
_HOME = f"https://{_HOST}/"
_LOCALE = f"https://{_HOST}/global/en"
_WD = "https://acmepharma.wd3.myworkdayjobs.com"
_CXS = f"{_WD}/wday/cxs/acmepharma/Acme_Careers_Site/jobs"
_SITEMAP = f"{_WD}/Acme_Careers_Site/siteMap.xml"


def _fx(name):
    return (_FX / name).read_text(encoding="utf-8")


@pytest.fixture
def session():
    return PoliteSession(min_delay=0, max_delay=0, timeout=5, max_retries=0)


def _det():
    return phenom.detect_cname(_HOST, "acmepharma.phenompeople.net", f"{_HOST} is a CNAME for acmepharma.phenompeople.net")


def _site(*, home="home.html", search="search_results.html"):
    """The career host as a Phenom front end serves it: the home page redirects to its locale."""
    responses.add(responses.GET, _HOME, status=302, headers={"Location": f"{_LOCALE}/home"})
    responses.add(responses.GET, f"{_LOCALE}/home", body=_fx(home))
    responses.add(responses.GET, f"{_LOCALE}/search-results", body=_fx(search))


def test_a_phenom_cname_is_named_and_cannot_be_followed_yet():
    det = _det()
    assert det.platform == "phenom" and det.entry is None and "Phenom" in det.evidence and det.refusal == "cant_yet"
    assert phenom.detect_cname("jobs.lego.com", "acme.github.io", "w") is None


@responses.activate
def test_a_workday_site_behind_phenom_that_lists_jobs_is_followed(session):
    _site()
    responses.add(responses.POST, _CXS, json={"total": 12, "jobPostings": [{"externalPath": "/job/x"}]})

    out = phenom.resolve(session, _det(), _HOME)

    assert (out.platform, out.entry) == ("career_sites", f"{_WD}/Acme_Careers_Site")
    assert "phenompeople" in out.evidence and "Acme_Careers_Site" in out.evidence and out.refusal is None
    assert out.config_key == "career_sites"


@responses.activate
def test_a_workday_site_with_an_empty_public_list_cannot_be_followed_yet(session):
    _site()
    responses.add(responses.POST, _CXS, json={"total": 0, "jobPostings": []})
    responses.add(responses.GET, _SITEMAP, body="<urlset></urlset>")

    out = phenom.resolve(session, _det(), _HOME)

    assert out.entry is None and out.platform == "phenom" and out.refusal == "cant_yet"
    assert "Workday" in out.evidence and "lists no jobs publicly" in out.evidence and "Acme_Careers_Site" in out.evidence


@responses.activate
def test_a_site_map_with_jobs_is_enough_when_the_job_list_says_nothing(session):
    _site()
    responses.add(responses.POST, _CXS, status=500)
    responses.add(responses.GET, _SITEMAP, body=f"<urlset><url><loc>{_WD}/Acme_Careers_Site/job/x_R1</loc></url></urlset>")

    out = phenom.resolve(session, _det(), _HOME)

    assert out.entry == f"{_WD}/Acme_Careers_Site"


@responses.activate
def test_a_job_page_is_read_when_the_search_page_shows_no_link(session):
    _site(search="search_results_no_link.html")
    responses.add(responses.GET, f"{_LOCALE}/job/R1001/Quality-Engineer", body=_fx("job_page.html"))
    responses.add(responses.POST, _CXS, json={"total": 3, "jobPostings": []})

    out = phenom.resolve(session, _det(), _HOME)

    assert out.entry == f"{_WD}/Acme_Careers_Site"


@responses.activate
def test_the_locale_comes_from_the_sitemap_when_the_home_page_names_none(session):
    responses.add(responses.GET, _HOME, body=_fx("home_no_locale.html"))
    responses.add(responses.GET, f"https://{_HOST}/sitemap.xml", body=_fx("sitemap.xml"))
    responses.add(responses.GET, f"{_LOCALE}/search-results", body=_fx("search_results.html"))
    responses.add(responses.POST, _CXS, json={"total": 5, "jobPostings": []})

    assert phenom.resolve(session, _det(), _HOME).entry == f"{_WD}/Acme_Careers_Site"


@responses.activate
def test_a_phenom_site_applying_to_another_system_cannot_be_followed_yet(session):
    _site(search="search_results_successfactors.html")

    out = phenom.resolve(session, _det(), _HOME)

    assert out.entry is None and out.refusal == "cant_yet" and "no link" in out.evidence


@responses.activate
def test_pages_that_cannot_be_read_leave_the_detection_alone(session):
    responses.add(responses.GET, _HOME, status=500)
    responses.add(responses.GET, f"https://{_HOST}/sitemap.xml", status=404)
    det = _det()
    assert phenom.resolve(session, det, _HOME) == det
