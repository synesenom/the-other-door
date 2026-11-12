"""A Jobaffinity apply link is looked through for the employer's name, which `_classify` then tries on the public
feeds (issue #563); when nothing is found the employer stays unfollowable ("cant_yet")."""

import re

import pytest
import responses

from door.commands import companies as companies_cmd
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "jobaffinity"
_AD = "https://jobaffinity.fr/apply/wqrlmvgzpyc67d0izf"
_TITLE = "Merchandiseur H/F"


def _company(name):
    return {"company": name, "links": [_AD], "postings": 1, "sources": {"jobindex"}, "titles": [_TITLE]}


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)
    monkeypatch.setattr(companies_cmd, "_cname", lambda host: None)
    monkeypatch.setattr(companies_cmd, "_resolves", lambda host: False)


def _classify(company):
    return companies_cmd._classify(companies_cmd._session(), dict(company), set())


def _form():
    return (_FX / "apply.html").read_text(encoding="utf-8")


@responses.activate
def test_the_employer_named_by_the_form_is_tried_on_the_feeds():
    responses.add(responses.GET, _AD, body=_form())
    responses.add(responses.GET, re.compile(r"https://boards-api\.greenhouse\.io/v1/boards/icciformations/jobs.*"),
                  json={"jobs": [{"id": 1, "title": _TITLE, "location": {"name": "Saint-Denis"}}]})
    responses.add(responses.GET, re.compile(r"https://.*"), status=404)

    kind, item = _classify(_company("Intuition"))

    assert (kind, item["platform"], item["entry"]) == ("suggestions", "greenhouse", "icciformations")


@responses.activate
def test_when_nothing_is_found_the_employer_stays_unfollowable_cant_yet():
    responses.add(responses.GET, _AD, body=_form())
    responses.add(responses.GET, re.compile(r"https://.*"), status=404)

    kind, item = _classify(_company("ICCI Formations"))

    assert (kind, item["platform"], item["refusal"]) == ("unfollowable", "jobaffinity", "cant_yet")


@responses.activate
def test_when_the_form_cannot_be_read_the_employer_stays_unfollowable_cant_yet():
    responses.add(responses.GET, _AD, status=403)
    responses.add(responses.GET, re.compile(r"https://.*"), status=404)

    kind, item = _classify(_company("ICCI Formations"))

    assert (kind, item["platform"], item["refusal"]) == ("unfollowable", "jobaffinity", "cant_yet")
