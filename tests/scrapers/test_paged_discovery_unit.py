"""The shared engine of the result-page discovery sources (`door.scrapers.paged_discovery`, handed to a
source as `sdk.paged_discovery`), on a fake source with fixed HTML: the stops of a run. What each real
source's pages look like is its own unit tests'; the whole crawl through each real source is
`tests/scrapers/discovery/test_page_sources_scrape.py`."""

import threading

from door.scrapers import drain_errors, drain_pushback, sdk
from door.scrapers import paged_discovery


class _Resp:
    def __init__(self, status, body, url):
        self.status_code, self.text, self.url = status, body, url


class _Session:
    def __init__(self, answers):
        self.answers, self.calls, self.headers = list(answers), [], {}

    def get(self, url, **_kwargs):
        self.calls.append(url)
        status, body, final = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return _Resp(status, body, final or url)

    def close(self):
        pass


def _cards(html):
    return [{"platform_id": f"{html}{i}", "title": "Data", "company": f"Firm {html}{i}", "location": "", "url": ""}
            for i in range(2 if html == "full" else 1 if html == "short" else 0)]


def _discover(monkeypatch, answers, *, rotation=("a",), sleeps=None, **kwargs):
    session = _Session(answers)
    monkeypatch.setattr(paged_discovery.requests, "Session", lambda: session)

    def sleep(seconds, stop):
        (sleeps if sleeps is not None else []).append(seconds)
        return stop is not None and stop.is_set()

    monkeypatch.setattr(paged_discovery, "_sleep", sleep)
    drain_errors()
    drain_pushback("fake")
    options = dict(name="fake", search_url=lambda kw, page, config: f"https://fake.example/{kw}/{page}",
                   parse_cards=_cards, is_wall=lambda url: "login" in url, page_cap=3, full_page=2,
                   max_budget=4, min_pause=(1.0, 2.0), rotation=list(rotation), pause=(1.0, 2.0))
    options.update(kwargs)
    return session, sdk.paged_discovery({"search_keywords": ["data"]}, **options)


def test_stops_at_budget_wall_and_refusal(monkeypatch):
    # a short page has no next page; a full one goes on to the page cap
    session, result = _discover(monkeypatch, [(200, "short", None)])
    assert len(session.calls) == 1 and result["outcome"] == "ok" and result["searched"] == ["a"]
    session, result = _discover(monkeypatch, [(200, "full", None)])
    assert len(session.calls) == 3 and result["outcome"] == "ok"

    # a spent budget ends the run, the unreached keyword waits
    session, result = _discover(monkeypatch, [(200, "full", None)], rotation=("a", "b"), budget=2)
    assert result["outcome"] == "budget" and result["requests"] == 2 and result["searched"] == []
    assert not result["search_complete"] and result["employers"]

    # the engine's budget and pause are held to the source's own limits
    _, result = _discover(monkeypatch, [(200, "short", None)], budget=99, pause=(0.0, 0.0))
    assert result["budget"] == 4 and result["pause"] == [1.0, 2.0]

    # a wall stops the run, keeps what was read and records the pushback
    session, result = _discover(monkeypatch, [(200, "full", None), (200, "x", "https://fake.example/login")])
    assert result["outcome"] == "refused" and result["pushback"] and len(result["employers"]) == 2
    assert "fake" in drain_errors() and drain_pushback("fake") is True

    # a wall page where the results should be is a refusal too
    _, result = _discover(monkeypatch, [(200, "<title>Just a moment...</title>", None)])
    assert result["outcome"] == "refused" and "instead of the results" in result["stopped"]

    # a refusal status
    _, result = _discover(monkeypatch, [(429, "", None)])
    assert result["outcome"] == "refused" and result["first_429"] == {"after_requests": 0, "after_s": result["first_429"]["after_s"]}

    # a server error is tried once more, then stops without resting the source
    session, result = _discover(monkeypatch, [(500, "", None)])
    assert len(session.calls) == 2 and result["outcome"] == "error" and not result["pushback"]
    assert drain_pushback("fake") is False


def test_a_stop_set_before_the_first_request_reads_nothing(monkeypatch):
    stop = threading.Event()
    stop.set()
    sleeps = []
    session, result = _discover(monkeypatch, [(200, "full", None)], stop=stop, sleeps=sleeps)
    assert result["outcome"] == "cancelled" and not result["pushback"]
    assert session.calls == [] and result["employers"] == []


def test_a_stop_set_while_waiting_between_two_requests_ends_the_run(monkeypatch):
    stop = threading.Event()
    session = _Session([(200, "full", None)])
    monkeypatch.setattr(paged_discovery.requests, "Session", lambda: session)
    monkeypatch.setattr(paged_discovery, "_sleep", lambda seconds, s: (s.set(), True)[1])
    result = sdk.paged_discovery(
        {"search_keywords": ["data"]}, name="fake", search_url=lambda kw, page, config: f"https://fake.example/{page}",
        parse_cards=_cards, is_wall=lambda url: False, page_cap=3, full_page=2, max_budget=4, min_pause=(1.0, 2.0),
        rotation=["a"], stop=stop)
    assert len(session.calls) == 1 and result["outcome"] == "cancelled" and len(result["employers"]) == 2


def test_without_keywords_nothing_is_read(monkeypatch):
    session = _Session([(200, "full", None)])
    monkeypatch.setattr(paged_discovery.requests, "Session", lambda: session)
    result = sdk.paged_discovery({}, name="fake", search_url=lambda *a: "", parse_cards=_cards, is_wall=lambda url: False,
                                 page_cap=1, full_page=1, max_budget=1, min_pause=(1.0, 1.0), rotation=["a"])
    assert result["outcome"] == "ok" and session.calls == []


def _card(i, title, company, url=""):
    return {"platform_id": str(i), "title": title, "company": company, "location": "", "url": url}


def test_only_on_topic_titles_are_kept_and_grouped_by_employer_in_order_of_first_sight():
    config = {"search_keywords": ["project manager"]}
    cards = [_card(1, "Senior Project Manager", "Hooli AB", "https://x.example/1"), _card(2, "Cook", "Krog AB"),
             _card(3, "Project Manager", "HOOLI AB", "https://x.example/3"), _card(4, "Baker", "Lager AB"),
             _card(5, "Project Manager", "Alfa AB")]
    got = paged_discovery.employers_of(cards, config)
    assert [e["company"] for e in got] == ["Hooli AB", "Alfa AB"]
    assert got[0]["titles"] == ["Senior Project Manager", "Project Manager"]
    assert got[0]["links"] == ["https://x.example/1", "https://x.example/3"] and got[1]["links"] == []
    assert got[0]["job_ids"] == [] and got[0]["detailed"] is False
