"""Welcome to the Jungle / Welcome Kit links and embeds are recognised but not followed (issue #562)."""

import pytest

from door.core import ats_detect
from door.scrapers.feeds import welcometothejungle as wttj
from door.scrapers.http_client import PoliteSession


@pytest.mark.parametrize("url", [
    "https://www.welcometothejungle.com/fr/companies/doctolib",
    "https://www.welcometothejungle.com/en/companies/doctolib/jobs/data-analyst_paris",
    "https://acme.welcomekit.co/",
    "https://welcomekit.co/api/v1/embed?organization_reference=abc123",
])
def test_a_wttj_or_welcome_kit_link_is_named_but_not_followed(url):
    det = wttj.detect_url(url)
    assert det.platform == "welcometothejungle" and det.entry is None
    assert det.refusal == "must_not" and "Welcome to the Jungle" in det.evidence


def test_other_hosts_are_not_wttj():
    assert wttj.detect_url("https://www.doctolib.fr/careers") is None
    assert wttj.detect_url("https://acme.fr/?u=welcometothejungle.com") is None


@pytest.mark.parametrize("html", [
    '<script src="https://www.welcomekit.co/api/v1/embed?organization_reference=abc123"></script>',
    '<iframe src="https://welcomekit.co/embed/abc"></iframe>',
    '<script src="//www.welcometothejungle.com/assets/embed.js"></script>',
])
def test_a_page_that_embeds_the_widget_is_a_wttj_page(html):
    det = wttj.detect_html(html, "https://www.acme.fr/carrieres")
    assert det.platform == "welcometothejungle" and det.entry is None and det.refusal == "must_not"
    assert wttj.detect_html("<p>x</p>", "https://www.acme.fr/") is None


def test_a_plain_link_to_wttj_does_not_decide_the_platform():
    assert wttj.LINK_PLATFORMS == ()
    assert wttj.detect_html('<a href="https://www.welcometothejungle.com/fr/companies/acme">x</a>', "https://acme.fr/") is None


def test_the_dispatcher_knows_the_module():
    assert "welcometothejungle" in ats_detect.PRECEDENCE
    det = ats_detect.from_url("https://www.welcometothejungle.com/fr/companies/doctolib")
    assert (det.platform, det.entry, det.refusal) == ("welcometothejungle", None, "must_not")


@pytest.fixture
def session():
    return PoliteSession(min_delay=0, max_delay=0, timeout=5, max_retries=0)


def test_resolve_names_the_employer_from_a_company_page_slug_without_a_request(session):
    url = "https://www.welcometothejungle.com/fr/companies/le-bon-coin/jobs/x"
    det = wttj.resolve(session, wttj.detect_url(url), url)
    assert det.employer == "Le Bon Coin" and det.entry is None and det.refusal == "must_not"


def test_resolve_names_an_employers_own_site_from_a_page_that_embeds_the_widget(session):
    url = "https://carrieres.acme-industrie.fr/offres"
    det = wttj.resolve(session, wttj.detect_html('<script src="https://welcomekit.co/x"></script>', url), url)
    assert det.employer == "Acme Industrie" and det.entry is None


def test_resolve_leaves_a_link_with_no_name_alone(session):
    url = "https://acme.welcomekit.co/"
    det = wttj.detect_url(url)
    assert wttj.resolve(session, det, url) == det
