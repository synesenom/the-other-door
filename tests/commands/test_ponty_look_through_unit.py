"""A Ponty apply link is looked through for the employer's name and site, which `_classify` then follows
as it does any employer (issue #530): the site's own platform first, then the name's feeds."""

import re

import pytest
import responses

from door.commands import companies as companies_cmd
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "ponty"
_AGENCY_AD = "https://pnty-apply.ponty-system.se/aldeaexecutivesearch?id=74"
_OWN_AD = "https://pnty-apply.ponty-system.se/friday?id=5142&pnty_src=platsbanken"
_TITLE = "Marketing Lead"


def _company(link, name):
    return {"company": name, "links": [link], "postings": 1, "sources": {"jobindex"}, "titles": [_TITLE]}


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)
    monkeypatch.setattr(companies_cmd, "_cname", lambda host: None)
    monkeypatch.setattr(companies_cmd, "_resolves", lambda host: False)


def _form(name):
    return (_FX / name).read_text(encoding="utf-8")


def _no_board(*patterns):
    for pattern in patterns:
        responses.add(responses.GET, re.compile(pattern), status=404)


def _classify(company):
    return companies_cmd._classify(companies_cmd._session(), dict(company), set())


@responses.activate
def test_the_employers_own_site_named_by_the_form_is_followed():
    responses.add(responses.GET, _OWN_AD, body=_form("apply_employer.html"))
    responses.add(responses.GET, "https://friday.se",
                  body='<script src="https://boards.greenhouse.io/embed/job_board/js?for=friday"></script>')

    kind, item = _classify(_company(_OWN_AD, "Friday Väst AB"))

    assert (kind, item["platform"], item["entry"]) == ("suggestions", "greenhouse", "friday")
    assert "Ponty" in item["evidence"]


@responses.activate
def test_the_hiring_employers_name_on_an_agency_form_is_tried_on_the_feeds():
    responses.add(responses.GET, _AGENCY_AD, body=_form("apply_agency.html"))
    responses.add(responses.GET, re.compile(r"https://boards-api\.greenhouse\.io/v1/boards/pontytechnology/jobs.*"),
                  json={"jobs": [{"id": 1, "title": _TITLE, "location": {"name": "Stockholm"}}]})
    _no_board(r"https://.*")

    kind, item = _classify(_company(_AGENCY_AD, "Ponty Technology AB"))

    assert (kind, item["platform"], item["entry"]) == ("suggestions", "greenhouse", "pontytechnology")
    assert "Ponty" in item["evidence"]


@responses.activate
def test_when_nothing_is_found_the_employer_stays_unfollowable_cant_yet():
    responses.add(responses.GET, _AGENCY_AD, body=_form("apply_agency.html"))
    _no_board(r"https://.*")

    kind, item = _classify(_company(_AGENCY_AD, "Ponty Technology AB"))

    assert (kind, item["platform"], item["refusal"]) == ("unfollowable", "ponty", "cant_yet")


@responses.activate
def test_when_the_form_cannot_be_read_the_employer_stays_unfollowable_cant_yet():
    responses.add(responses.GET, _AGENCY_AD, status=403)
    _no_board(r"https://.*")

    kind, item = _classify(_company(_AGENCY_AD, "Ponty Technology AB"))

    assert (kind, item["platform"], item["refusal"]) == ("unfollowable", "ponty", "cant_yet")
