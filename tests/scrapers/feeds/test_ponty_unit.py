"""Ponty apply links are recognised but not followed (issue #530): the system has no public job list."""

import pytest

from door.scrapers.feeds import ponty
from door.scrapers.sdk import PoliteSession


@pytest.mark.parametrize("url", [
    "https://pnty-apply.ponty-system.se/aldeaexecutivesearch?id=74",
    "https://acme.ponty-system.se/jobs?id=3",
    "https://ponty-system.se/apply?id=9",
])
def test_a_ponty_link_is_named_but_not_followed(url):
    det = ponty.detect_url(url)
    assert det.platform == "ponty" and det.entry is None and det.refusal == "cant_yet"
    assert "Ponty" in det.evidence and "no public job list" in det.evidence


def test_other_hosts_are_not_ponty():
    assert ponty.detect_url("https://acme.se/karriar") is None
    assert ponty.detect_url("https://www.ponty.se/") is None
    assert ponty.detect_url("https://notponty-system.se/x") is None


def test_a_page_that_embeds_the_ponty_form_is_a_ponty_site():
    html = '<iframe src="https://pnty-apply.ponty-system.se/acme?id=3"></iframe>'
    det = ponty.detect_html(html, "https://acme.se/karriar")
    assert det.platform == "ponty" and det.entry is None
    assert ponty.detect_html("<p>x</p>", "https://acme.se/") is None


def test_a_link_to_ponty_does_not_decide_which_platform_a_page_is_on():
    assert ponty.LINK_PLATFORMS == ()
    assert "ponty-system.se" in ponty.PLATFORM_DOMAINS


# --- the look-through (the apply form names the hiring employer) ------------------------------------------------

import requests
import responses

from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "ponty"
_AGENCY_URL = "https://pnty-apply.ponty-system.se/aldeaexecutivesearch?id=74"
_EMPLOYER_URL = "https://pnty-apply.ponty-system.se/friday?id=5142&pnty_src=platsbanken"


def _form(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


def test_a_form_for_a_client_of_an_agency_names_the_client_not_the_agency_or_its_site():
    # The customer (Aldea Executive Search) is an agency: its privacy link is not the hiring employer's site.
    assert ponty.employer_of(_form("apply_agency.html")) == ("Ponty Technology", None)


def test_a_form_without_a_client_name_gives_the_customers_own_site_from_its_policy_link():
    assert ponty.employer_of(_form("apply_employer.html")) == (None, "https://friday.se")


def test_the_client_name_is_unescaped_and_its_own_policy_link_is_its_site():
    html = ('<h2 class="sub-legend">Smith &amp; Söner AB</h2><div class="consent-wrapper"><p>Policy för Smith &amp; Söner AB: '
            '<a href="https://www.smithsoner.se/gdpr">här</a></p></div>')
    assert ponty.employer_of(html) == ("Smith & Söner AB", "https://www.smithsoner.se")


@pytest.mark.parametrize("link", [
    "mailto:dpo@example.com",
    "https://pnty-apply.ponty-system.se/x",
    "https://www.ponty.se/integritet",
    "https://www.glassdoor.com/job-listing/1",
    "/relative/policy",
])
def test_links_that_are_not_an_employers_own_site_are_rejected(link):
    html = f'<div class="consent-wrapper"><p>Policy <a href="{link}">här</a></p></div>'
    assert ponty.employer_of(html) == (None, None)


def test_a_page_without_a_form_names_nobody():
    assert ponty.employer_of("<html><body><h1>Configuration error</h1></body></html>") == (None, None)
    assert ponty.employer_of("") == (None, None)


@responses.activate
def test_resolve_reads_the_form_in_one_request_and_carries_the_employer():
    responses.add(responses.GET, _AGENCY_URL, body=_form("apply_agency.html"))
    det = ponty.detect_url(_AGENCY_URL)

    out = ponty.resolve(PoliteSession(min_delay=0, max_delay=0), det, _AGENCY_URL)

    assert (out.platform, out.entry, out.refusal) == ("ponty", None, "cant_yet")
    assert (out.employer, out.site) == ("Ponty Technology", None)
    assert "Ponty Technology" in out.evidence
    assert len(responses.calls) == 1


@responses.activate
def test_resolve_hands_over_the_site_when_the_form_has_no_client_name():
    responses.add(responses.GET, _EMPLOYER_URL, body=_form("apply_employer.html"))
    det = ponty.detect_url(_EMPLOYER_URL)

    out = ponty.resolve(PoliteSession(min_delay=0, max_delay=0), det, _EMPLOYER_URL)

    assert (out.employer, out.site) == (None, "https://friday.se")


@pytest.mark.parametrize("reply", [
    {"status": 403},
    {"status": 500},
    {"body": "<html>Configuration error</html>"},
    {"body": requests.ConnectionError("down")},
])
@responses.activate
def test_resolve_leaves_the_detection_unchanged_when_the_form_cannot_be_read(reply):
    responses.add(responses.GET, _AGENCY_URL, **reply)
    det = ponty.detect_url(_AGENCY_URL)

    assert ponty.resolve(PoliteSession(min_delay=0, max_delay=0, max_retries=0), det, _AGENCY_URL) is det


def test_resolve_ignores_a_link_that_is_not_an_apply_form():
    det = ponty.detect_url("https://ponty-system.se/")
    # no request is mocked: any network use would fail the suite
    assert ponty.resolve(PoliteSession(min_delay=0, max_delay=0), det, "https://ponty-system.se/") is det
