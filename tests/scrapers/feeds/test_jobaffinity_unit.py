"""Jobaffinity apply links are recognised but not followed (issue #563): the system has no public job list."""

import pytest
import requests
import responses

from door.scrapers.feeds import jobaffinity
from door.scrapers.sdk import PoliteSession
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "jobaffinity"
_URL = "https://jobaffinity.fr/apply/wqrlmvgzpyc67d0izf"


def _form() -> str:
    return (_FX / "apply.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("url", [
    _URL,
    "https://www.jobaffinity.fr/apply/abc123",
    "https://acme.jobaffinity.com/apply/abc123",
])
def test_a_jobaffinity_link_is_named_but_not_followed(url):
    det = jobaffinity.detect_url(url)
    assert det.platform == "jobaffinity" and det.entry is None and det.refusal == "cant_yet"
    assert "Jobaffinity" in det.evidence and "no public job list" in det.evidence


def test_other_hosts_are_not_jobaffinity():
    assert jobaffinity.detect_url("https://acme.fr/recrutement") is None
    assert jobaffinity.detect_url("https://notjobaffinity.fr/apply/x") is None


def test_a_page_that_links_the_apply_form_is_a_jobaffinity_site():
    html = '<a href="https://jobaffinity.fr/apply/abc123">Postuler</a>'
    det = jobaffinity.detect_html(html, "https://acme.fr/recrutement")
    assert det.platform == "jobaffinity" and det.entry is None
    assert jobaffinity.detect_html("<p>x</p>", "https://acme.fr/") is None


def test_a_link_to_jobaffinity_does_not_decide_which_platform_a_page_is_on():
    assert jobaffinity.LINK_PLATFORMS == ()
    assert "jobaffinity.fr" in jobaffinity.PLATFORM_DOMAINS


def test_the_form_names_the_data_controller_as_the_employer():
    assert jobaffinity.employer_of(_form()) == "ICCI Formations"


def test_the_other_usual_wording_of_the_notice_is_read_too():
    html = '<p>Vos données sont traitées par Mairie de Saint-Denis, responsable de traitement, pour votre candidature.</p>'
    assert jobaffinity.employer_of(html) == "Mairie de Saint-Denis"


@pytest.mark.parametrize("html", ["", "<p>Rien ici</p>", "<p>traitement automatisé par</p>"])
def test_a_form_that_names_no_one_gives_none(html):
    assert jobaffinity.employer_of(html) is None


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)
    return PoliteSession(min_delay=0, max_delay=0, timeout=5, max_retries=0)


@responses.activate
def test_resolve_adds_the_employer_the_form_names(session):
    responses.add(responses.GET, _URL, body=_form())
    det = jobaffinity.detect_url(_URL)
    out = jobaffinity.resolve(session, det, _URL)
    assert out.platform == "jobaffinity" and out.entry is None and out.refusal == "cant_yet"
    assert out.employer == "ICCI Formations" and out.site is None
    assert len(responses.calls) == 1


@responses.activate
def test_resolve_keeps_the_detection_when_the_form_cannot_be_read_or_names_no_one(session):
    det = jobaffinity.detect_url(_URL)
    responses.add(responses.GET, _URL, status=404)
    assert jobaffinity.resolve(session, det, _URL) is det
    responses.replace(responses.GET, _URL, body="<p>Rien</p>")
    assert jobaffinity.resolve(session, det, _URL) is det
    responses.replace(responses.GET, _URL, body=requests.ConnectionError("down"))
    assert jobaffinity.resolve(session, det, _URL) is det


@responses.activate
def test_resolve_reads_only_an_apply_form(session):
    det = jobaffinity.detect_url("https://jobaffinity.fr/")
    assert jobaffinity.resolve(session, det, "https://jobaffinity.fr/") is det
    assert len(responses.calls) == 0
