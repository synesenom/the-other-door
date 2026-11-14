"""Fixture tests for the result-page discovery sources (`hellowork.run`, `jobbsafari.run`,
`profession.run`): the whole crawl in a fake HTTP session that serves result pages (synthetic
ones in each site's shape, fixtures/<source>/, and pages built from a card template). No network,
no waiting (each module's `_sleep` is faked). The crawl rules are the same for the three; what each
site's pages look like is its adapter here and its unit tests."""

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest
import responses

from door.scrapers import drain_errors, drain_pushback
from door.scrapers import sdk
from door.scrapers.discovery import hellowork, jobbsafari, profession

_FIX = Path(__file__).parent / "fixtures"
_PAUSE = (3.0, 6.0)
_KEYS = {"employers", "details", "pages", "requests", "stopped", "pushback", "outcome", "mode", "mode_switched",
         "searched", "search_complete", "first_429", "budget", "pause", "seconds"}


def _hellowork_page(first, n):
    def card(i):
        return (f'<li data-id-storage-target="item" data-id-storage-item-id="{i}">'
                f'<input type="hidden" name="title" value="Chef de Projet H/F"><input type="hidden" name="company" value="Firm {i} SAS">'
                f'<a data-cy="offerTitle" href="/fr-fr/emplois/{i}.html?src=a"></a>'
                f'<div data-cy="localisationCard">Paris - 75</div></li>')
    return "<ul>" + "".join(card(i) for i in range(first, first + n)) + "</ul>"


def _jobbsafari_page(first, n):
    def entry(i):
        return {"pk": i, "title": "Project Manager", "company": {"name": f"Firm {i} AB"}, "locations": [{"name": "Stockholm"}],
                "apply": {"method": "url", "href": f"https://careers.example.com/job/{i}?utm_source=jobbsafari.se&utm_medium=referral"}}
    data = {"props": {"pageProps": {"jobEntries": {"count": 999, "results": [entry(i) for i in range(first, first + n)]}}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'


def _profession_page(first, n):
    def card(i):
        return (f'<li class="advertisement-result-list-item" data-item-id="{i}" data-item-name="Data Scientist" '
                f'data-item-brand="Firm {i} Kft." data-link="https://www.profession.hu/allas/x-{i}?keyword=a&amp;hash=b">'
                f'<li id="detailed-job-card-{i}-details-location" title="Budapest"></li></li>')
    return "<ul>" + "".join(card(i) for i in range(first, first + n)) + "</ul>"


def _hellowork_first_run(employers):
    hooli = next(e for e in employers if e["company"].startswith("Hooli"))
    assert hooli["links"][0].startswith("https://www.hellowork.com/fr-fr/emplois/") and "?" not in hooli["links"][0]
    return hooli


def _jobbsafari_first_run(employers):
    wayne = next(e for e in employers if e["company"].startswith("Wayne"))
    assert wayne["links"] == ["https://wayne.wd1.myworkdayjobs.com/External/job/Project-Manager_R000001"]
    assert next(e for e in employers if e["company"].startswith("Vandelay"))["links"] == []   # applies by mail
    return wayne


def _profession_first_run(employers):
    acme = next(e for e in employers if e["company"].startswith("Acme"))
    assert acme["links"][0].startswith("https://www.profession.hu/allas/") and "?" not in acme["links"][0]
    return acme


@dataclass
class Source:
    module: object
    keyword: str
    other_keyword: str
    city: str
    search: re.Pattern            # every result-page URL
    first_page: str               # a pattern for the real session's first request
    page: Callable                # page(first, n): a result page of n made-up cards
    size: int                     # cards on a full page
    page2_fixture: str
    page2_url_end: str
    page2_names: set
    check_first_run: Callable     # site-specific checks of the employers read; returns one employer
    walls: tuple                  # final URLs off the listing

    @property
    def name(self):
        return self.module.NAME

    def config(self):
        return {"search_keywords": [self.keyword], "location": self.city}

    def fx(self, name):
        return (_FIX / self.name / name).read_text(encoding="utf-8")


_SOURCES = {
    "hellowork": Source(
        hellowork, "chef de projet", "ingénieur données", "Paris",
        re.compile(r"https://www\.hellowork\.com/fr-fr/emploi/recherche\.html\?k=([^&]*)&l=Paris(?:&p=(\d+))?$"),
        r"https://www\.hellowork\.com/fr-fr/emploi/recherche\.html\?k=.*",
        _hellowork_page, 30, "search_chef_de_projet_p2.html", "?k=chef+de+projet&l=Paris&p=2",
        {"Firm 1 SAS", "Firm 30 SAS", "Hooli.", "Mon Consultant Fictif"}, _hellowork_first_run,
        ("https://www.hellowork.com/fr-fr/candidat/connexion", "https://www.hellowork.com/fr-fr/page/captcha",
         "https://elsewhere.example.com/fr-fr/emploi/recherche.html")),
    "jobbsafari": Source(
        jobbsafari, "project manager", "projektledare", "Stockholm",
        re.compile(r"https://jobbsafari\.se/lediga-jobb\?sok=(.*)$"), r"https://jobbsafari\.se/lediga-jobb\?sok=.*",
        _jobbsafari_page, 30, "search_project_manager_p2.html", "&page=2",
        {"Firm 1 AB", "Firm 30 AB", "Umbrella Professionals AB", "Wayne & Partners", "Vandelay Technologies Sweden AB"},
        _jobbsafari_first_run,
        ("https://jobbsafari.se/logga-in", "https://jobbsafari.se/konto", "https://elsewhere.example.com/lediga-jobb?sok=x")),
    "profession": Source(
        profession, "data scientist", "adatelemző", "Budapest",
        re.compile(r"https://www\.profession\.hu/allasok/(\d+),0,0,(.*)$"), r"https://www\.profession\.hu/allasok/1,0,0,.*",
        _profession_page, 20, "search_data_scientist_p2.html", "/allasok/2,0,0,data%20scientist",
        {"Firm 1 Kft.", "Firm 20 Kft.", "Acme Biztosító Zrt.", "Hooli Hungary Kft."}, _profession_first_run,
        ("https://www.profession.hu/login", "https://www.profession.hu/fiok/belepes", "https://elsewhere.example.com/allasok/1,0,0,x")),
}


class _Response:
    def __init__(self, status, body):
        self.status, self._body = status, body

    def text(self):
        return self._body


class _Page:
    """Answers per URL in order, repeating the last; an answer is (status, body, final_url) or an exception."""

    def __init__(self):
        self.routes, self.calls, self.url = [], [], ""

    def add(self, pattern, body="", status=200, final_url=None, raises=None):
        answer = raises or (status, body, final_url)
        for pat, answers in self.routes:
            if pat is pattern:
                answers.append(answer)
                return
        self.routes.append((pattern, [answer]))

    def goto(self, url, **kwargs):
        self.calls.append(url)
        for pat, answers in self.routes:
            if pat.match(url):
                answer = answers.pop(0) if len(answers) > 1 else answers[0]
                if isinstance(answer, BaseException):
                    raise answer
                status, body, final_url = answer
                self.url = final_url or url
                return _Response(status, body)
        raise AssertionError(f"unexpected goto {url}")


class _Session:
    def __init__(self):
        self.page, self.closed = _Page(), False

    def close(self):
        self.closed = True


@pytest.fixture(params=sorted(_SOURCES))
def src(request):
    return _SOURCES[request.param]


@pytest.fixture
def session(src, monkeypatch):
    s = _Session()
    monkeypatch.setattr(src.module, "_open_session", lambda: s)
    drain_errors()
    drain_pushback(src.name)
    return s


@pytest.fixture
def sleeps(src, monkeypatch):
    out = []

    def fake_sleep(seconds, stop=None):
        out.append(seconds)
        return stop.is_set() if stop is not None else False

    monkeypatch.setattr(src.module, "_sleep", fake_sleep)
    return out


@pytest.fixture(autouse=True)
def _no_waiting(sleeps):
    """Every test runs with the fake sleep."""


def _run(src, config=None, **kwargs):
    kwargs.setdefault("budget", 30)
    kwargs.setdefault("pause", _PAUSE)
    kwargs.setdefault("mode", "rotate")
    kwargs.setdefault("rotation", [src.keyword])
    return src.module.run(config or src.config(), **kwargs)


def _pages(src, session, *bodies):
    for body in bodies:
        session.page.add(src.search, body)


def _full(src, k):
    """The k-th full page (from 0)."""
    return src.page(1 + k * src.size, src.size)


def test_a_full_page_then_a_short_one_end_the_keyword_and_queue_the_on_topic_employers(src, session):
    _pages(src, session, _full(src, 0), src.fx(src.page2_fixture))
    result = _run(src)
    assert set(result) >= _KEYS
    assert len(session.page.calls) == 2 and session.page.calls[1].endswith(src.page2_url_end)
    assert result["outcome"] == "ok" and result["search_complete"] and result["mode"] == "rotate"
    assert result["searched"] == [src.keyword] and result["requests"] == result["pages"] == 2 and result["details"] == 0
    assert src.page2_names <= {e["company"] for e in result["employers"]}
    one = src.check_first_run(result["employers"])
    assert one["job_ids"] == [] and one["first_seen"]
    assert session.closed and drain_errors() == {}


def test_a_keyword_stops_at_the_page_cap(src, session):
    _pages(src, session, *(_full(src, k) for k in range(4)))
    result = _run(src)
    assert len(session.page.calls) == src.module._PAGE_CAP == 3
    assert result["search_complete"] and result["outcome"] == "ok"


def test_an_id_on_two_pages_counts_once(src, session):
    _pages(src, session, _full(src, 0), src.page(1, 5))
    assert len(_run(src)["employers"]) == src.size


def test_a_small_budget_ends_the_run_and_the_unreached_keywords_wait(src, session):
    _pages(src, session, *(_full(src, k) for k in range(3)))
    result = _run(src, budget=2, rotation=[src.keyword, src.other_keyword])
    assert result["outcome"] == "budget" and not result["search_complete"] and result["requests"] == 2
    assert result["searched"] == [] and result["employers"]


def test_the_budget_and_pause_of_the_engine_are_clamped_to_this_sources_own_limits(src, session):
    _pages(src, session, src.fx(src.page2_fixture))
    result = _run(src, budget=150, pause=(2.0, 4.0))
    assert result["budget"] == src.module._MAX_BUDGET == 30 and result["pause"] == [3.0, 6.0]
    assert _run(src, budget=150, pause=(8.0, 16.0))["pause"] == [8.0, 16.0]


def test_it_pauses_between_requests_not_before_the_first(src, session, sleeps):
    _pages(src, session, _full(src, 0), src.fx(src.page2_fixture))
    _run(src)
    assert len(sleeps) == 1 and 3 <= sleeps[0] <= 6


@pytest.mark.parametrize("status", [429, 403])
def test_a_refusal_stops_at_once_keeps_the_employers_read_and_is_recorded(src, session, status):
    _pages(src, session, _full(src, 0))
    session.page.add(src.search, status=status)
    result = _run(src)
    assert len(session.page.calls) == 2 and result["stopped"] == f"HTTP {status}" and result["pushback"]
    assert result["outcome"] == "refused" and len(result["employers"]) == src.size
    assert src.name in drain_errors() and drain_pushback(src.name) is True and session.closed
    if status == 429:
        assert result["first_429"] == {"after_requests": 1, "after_s": result["first_429"]["after_s"]}


def test_a_server_error_is_retried_once_then_stops_without_pushback(src, session):
    session.page.add(src.search, status=500)
    result = _run(src)
    assert len(session.page.calls) == 2 and result["outcome"] == "error" and not result["pushback"]
    assert src.name in drain_errors() and drain_pushback(src.name) is False


def test_one_transient_error_is_retried(src, session):
    session.page.add(src.search, raises=TimeoutError("timed out"))
    _pages(src, session, src.fx(src.page2_fixture))
    result = _run(src)
    assert result["outcome"] == "ok" and result["requests"] == 2 and drain_errors() == {}


@pytest.mark.parametrize("which", [0, 1, 2])
def test_a_redirect_off_the_listing_stops_as_a_refusal(src, session, which):
    session.page.add(src.search, "<html>x</html>", final_url=src.walls[which])
    result = _run(src)
    assert result["outcome"] == "refused" and result["pushback"] and drain_pushback(src.name) is True


def test_a_stop_signal_ends_the_run_before_the_next_request(src, session):
    stop = threading.Event()
    _pages(src, session, _full(src, 0))
    goto = session.page.goto

    def goto_then_stop(url, **kwargs):
        response = goto(url, **kwargs)
        stop.set()
        return response

    session.page.goto = goto_then_stop
    result = _run(src, stop=stop)
    assert len(session.page.calls) == 1 and result["outcome"] == "cancelled" and not result["pushback"]
    assert len(result["employers"]) == src.size


def test_without_keywords_nothing_is_requested(src, session):
    result = _run(src, {"location": src.city})
    assert session.page.calls == [] and result["employers"] == [] and set(result) >= _KEYS


def test_run_accepts_the_engines_other_arguments(src, session):
    assert src.module.run({"location": src.city}, since=None, keyword_since={}, known_companies=frozenset(),
                          stop=None, pending={})["employers"] == []


@responses.activate
def test_the_real_session_sends_the_user_agent_and_no_cookies_or_credentials(src):
    responses.add(responses.GET, re.compile(src.first_page), body=src.page(1, 3), headers={"Set-Cookie": "sid=abc; Path=/"})
    result = _run(src)
    sent = responses.calls[0].request
    assert "Cookie" not in sent.headers and "Authorization" not in sent.headers
    assert sent.headers["User-Agent"] == sdk.USER_AGENT
    assert len(result["employers"]) == 3
    _run(src)   # nothing carries over: the next run starts a fresh session
    assert "Cookie" not in responses.calls[1].request.headers


@pytest.mark.parametrize("wall", [
    "<html><head><title>Just a moment...</title></head><body></body></html>",
    "<html><head><title>Cookie consent</title></head><body>Accept all</body></html>",
])
def test_a_wall_page_instead_of_the_results_stops_as_a_refusal_not_as_no_employers(src, session, wall):
    """A captcha, a bot challenge or a consent page is a refusal (#19): rested, never "no employers"."""
    _pages(src, session, wall)
    result = _run(src)
    assert result["outcome"] == "refused" and result["pushback"] and "instead of the results" in result["stopped"]
    assert drain_pushback(src.name) is True


def test_a_block_page_sent_with_a_server_error_is_a_refusal_not_a_failing_server(src, session):
    """profession.hu's firewall answers 500 with "The URL you requested has been blocked" (#19)."""
    session.page.add(src.search, "<html><head><title>The URL you requested has been blocked</title></head></html>", status=500)
    result = _run(src)
    assert result["outcome"] == "refused" and result["pushback"] and len(session.page.calls) == 1
    assert drain_pushback(src.name) is True
