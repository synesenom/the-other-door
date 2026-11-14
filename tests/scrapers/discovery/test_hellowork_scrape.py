"""Fixture tests for HelloWork employer discovery (`hellowork.run`): the whole crawl in a fake
HTTP session that serves result pages (synthetic ones in the site's shape, fixtures/hellowork/, and
pages built from a card template). No network, no waiting (`hellowork._sleep` is faked)."""

import re
import threading
from pathlib import Path

import pytest
import requests
import responses

from door.scrapers import drain_errors, drain_pushback
from door.scrapers import sdk
from door.scrapers.discovery import hellowork

_FIX = Path(__file__).parent / "fixtures" / "hellowork"
_CONFIG = {"search_keywords": ["chef de projet"], "location": "Paris"}
_PAUSE = (3.0, 6.0)
_SEARCH = re.compile(r"https://www\.hellowork\.com/fr-fr/emploi/recherche\.html\?k=([^&]*)&l=Paris(?:&p=(\d+))?$")
_REAL_OPEN_SESSION = hellowork._open_session
_KEYS = {"employers", "details", "pages", "requests", "stopped", "pushback", "outcome", "mode", "mode_switched",
         "searched", "search_complete", "first_429", "budget", "pause", "seconds"}


def _fx(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


def _card(i, title="Chef de Projet H/F", company=None):
    company = company or f"Firm {i} SAS"
    return (f'<li data-id-storage-target="item" data-id-storage-item-id="{i}">'
            f'<input type="hidden" name="title" value="{title}"><input type="hidden" name="company" value="{company}">'
            f'<a data-cy="offerTitle" href="/fr-fr/emplois/{i}.html?src=a"></a>'
            f'<div data-cy="localisationCard">Paris - 75</div></li>')


def _page(first, n=30):
    return "<ul>" + "".join(_card(i) for i in range(first, first + n)) + "</ul>"


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


@pytest.fixture(autouse=True)
def session(monkeypatch):
    s = _Session()
    monkeypatch.setattr(hellowork, "_open_session", lambda: s)
    drain_errors()
    drain_pushback("hellowork")
    return s


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    out = []

    def fake_sleep(seconds, stop=None):
        out.append(seconds)
        return stop.is_set() if stop is not None else False

    monkeypatch.setattr(hellowork, "_sleep", fake_sleep)
    return out


def _run(config=None, **kwargs):
    kwargs.setdefault("budget", 30)
    kwargs.setdefault("pause", _PAUSE)
    kwargs.setdefault("mode", "rotate")
    kwargs.setdefault("rotation", ["chef de projet"])
    return hellowork.run(config or _CONFIG, **kwargs)


def _pages(session, *bodies):
    for body in bodies:
        session.page.add(_SEARCH, body)


def test_a_full_page_then_a_short_one_end_the_keyword_and_queue_the_on_topic_employers(session):
    _pages(session, _page(1), _fx("search_chef_de_projet_p2.html"))
    result = _run()
    assert set(result) >= _KEYS
    assert len(session.page.calls) == 2 and session.page.calls[1].endswith("?k=chef+de+projet&l=Paris&p=2")
    assert result["outcome"] == "ok" and result["search_complete"] and result["mode"] == "rotate"
    assert result["searched"] == ["chef de projet"] and result["requests"] == result["pages"] == 2 and result["details"] == 0
    names = {e["company"] for e in result["employers"]}
    assert {"Firm 1 SAS", "Firm 30 SAS", "Hooli.", "Mon Consultant Fictif"} <= names
    hooli = next(e for e in result["employers"] if e["company"].startswith("Hooli"))
    assert hooli["links"] and hooli["links"][0].startswith("https://www.hellowork.com/fr-fr/emplois/") and "?" not in hooli["links"][0]
    assert hooli["job_ids"] == [] and hooli["first_seen"]
    assert session.closed and drain_errors() == {}


def test_a_keyword_stops_at_the_page_cap(session):
    _pages(session, _page(1), _page(31), _page(61), _page(91))
    result = _run()
    assert len(session.page.calls) == hellowork._PAGE_CAP == 3
    assert result["search_complete"] and result["outcome"] == "ok"


def test_an_id_on_two_pages_counts_once(session):
    _pages(session, _page(1), _page(1, 5))
    result = _run()
    assert len(result["employers"]) == 30


def test_a_small_budget_ends_the_run_and_the_unreached_keywords_wait(session):
    _pages(session, _page(1), _page(31), _page(61))
    result = _run(budget=2, rotation=["chef de projet", "ingénieur données"])
    assert result["outcome"] == "budget" and not result["search_complete"] and result["requests"] == 2
    assert result["searched"] == [] and result["employers"]


def test_the_budget_and_pause_of_the_engine_are_clamped_to_this_sources_own_limits(session):
    _pages(session, _fx("search_chef_de_projet_p2.html"))
    result = _run(budget=150, pause=(2.0, 4.0))
    assert result["budget"] == hellowork._MAX_BUDGET == 30 and result["pause"] == [3.0, 6.0]
    result = _run(budget=150, pause=(8.0, 16.0))
    assert result["pause"] == [8.0, 16.0]


def test_it_pauses_between_requests_not_before_the_first(session, sleeps):
    _pages(session, _page(1), _fx("search_chef_de_projet_p2.html"))
    _run()
    assert len(sleeps) == 1 and 3 <= sleeps[0] <= 6


@pytest.mark.parametrize("status", [429, 403])
def test_a_refusal_stops_at_once_keeps_the_employers_read_and_is_recorded(session, status):
    _pages(session, _page(1))
    session.page.add(_SEARCH, status=status)
    result = _run()
    assert len(session.page.calls) == 2 and result["stopped"] == f"HTTP {status}" and result["pushback"]
    assert result["outcome"] == "refused" and len(result["employers"]) == 30
    assert "hellowork" in drain_errors() and drain_pushback("hellowork") is True and session.closed
    if status == 429:
        assert result["first_429"] == {"after_requests": 1, "after_s": result["first_429"]["after_s"]}


def test_a_server_error_is_retried_once_then_stops_without_pushback(session):
    session.page.add(_SEARCH, status=500)
    result = _run()
    assert len(session.page.calls) == 2 and result["outcome"] == "error" and not result["pushback"]
    assert "hellowork" in drain_errors() and drain_pushback("hellowork") is False


def test_one_transient_error_is_retried(session):
    session.page.add(_SEARCH, raises=TimeoutError("timed out"))
    _pages(session, _fx("search_chef_de_projet_p2.html"))
    result = _run()
    assert result["outcome"] == "ok" and result["requests"] == 2 and drain_errors() == {}


@pytest.mark.parametrize("final", ["https://www.hellowork.com/fr-fr/candidat/connexion", "https://www.hellowork.com/fr-fr/page/captcha",
                                   "https://elsewhere.example.com/fr-fr/emploi/recherche.html"])
def test_a_redirect_off_the_listing_stops_as_a_refusal(session, final):
    session.page.add(_SEARCH, "<html>x</html>", final_url=final)
    result = _run()
    assert result["outcome"] == "refused" and result["pushback"] and drain_pushback("hellowork") is True


def test_a_stop_signal_ends_the_run_before_the_next_request(session):
    stop = threading.Event()
    _pages(session, _page(1))
    goto = session.page.goto

    def goto_then_stop(url, **kwargs):
        response = goto(url, **kwargs)
        stop.set()
        return response

    session.page.goto = goto_then_stop
    result = _run(stop=stop)
    assert len(session.page.calls) == 1 and result["outcome"] == "cancelled" and not result["pushback"]
    assert len(result["employers"]) == 30


def test_without_keywords_nothing_is_requested(session):
    result = _run({"location": "Paris"})
    assert session.page.calls == [] and result["employers"] == [] and set(result) >= _KEYS


def test_run_accepts_the_engines_other_arguments():
    assert hellowork.run({"location": "Paris"}, since=None, keyword_since={}, known_companies=frozenset(),
                          stop=None, pending={}) ["employers"] == []


@responses.activate
def test_the_real_session_sends_the_door_user_agent_and_no_cookies_or_credentials(monkeypatch):
    monkeypatch.setattr(hellowork, "_open_session", _REAL_OPEN_SESSION)
    responses.add(responses.GET, re.compile(r"https://www\.hellowork\.com/fr-fr/emploi/recherche\.html\?k=.*"), body=_page(1, 3),
                  headers={"Set-Cookie": "sid=abc; Path=/"})
    result = _run()
    sent = responses.calls[0].request
    assert "Cookie" not in sent.headers and "Authorization" not in sent.headers
    assert sent.headers["User-Agent"] == sdk.USER_AGENT
    assert len(result["employers"]) == 3
    # nothing carries over: the next run starts a fresh session
    _run()
    assert "Cookie" not in responses.calls[1].request.headers


def test_the_module_never_logs_in_or_keeps_credentials():
    text = Path(hellowork.__file__).read_text(encoding="utf-8")
    for word in ("Authorization", "password", "cookies.set", "print("):
        assert word not in text


@pytest.mark.parametrize("wall", [
    "<html><head><title>Just a moment...</title></head><body></body></html>",
    "<html><head><title>Cookie consent</title></head><body>Accept all</body></html>",
])
def test_a_wall_page_instead_of_the_results_stops_as_a_refusal_not_as_no_employers(session, wall):
    """A captcha, a bot challenge or a consent page is a refusal (#19): rested, never "no employers"."""
    _pages(session, wall)
    result = _run()
    assert result["outcome"] == "refused" and result["pushback"] and "instead of the results" in result["stopped"]
    assert drain_pushback("hellowork") is True


def test_a_block_page_sent_with_a_server_error_is_a_refusal_not_a_failing_server(session):
    """profession.hu's firewall answers 500 with "The URL you requested has been blocked" (#19)."""
    session.page.add(_SEARCH, "<html><head><title>The URL you requested has been blocked</title></head></html>", status=500)
    result = _run()
    assert result["outcome"] == "refused" and result["pushback"] and len(session.page.calls) == 1
    assert drain_pushback("hellowork") is True
