"""Fixture tests for LinkedIn employer discovery (`linkedin.discover_run`): the logged-out guest
endpoints, loaded in a fake browser page that serves synthetic pages in their shape
(fixtures/linkedin/). `search_results_2.html` is two made-up cards (one repeating a card
of page one) as a second page; `_cards` builds other pages. No network, no browser,
no waiting (`linkedin._sleep` is faked)."""

import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from door.scrapers import drain_errors, drain_pushback, http_client
from door.scrapers.discovery import linkedin

_FIX = Path(__file__).parent / "fixtures" / "linkedin"
_SEARCH = re.compile(re.escape(linkedin._SEARCH_URL) + r"(\?.*)?$")
_DETAIL = re.compile(re.escape(linkedin._DETAIL_URL.format(id="")) + r"\d+$")
_CONFIG = {"search_keywords": ["data scientist"], "location": "Copenhagen"}
_APPLY = '<code id="applyUrl"><!--"{url}"--></code>'
_EMPTY = "<!DOCTYPE html>\n"


def _fx(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


class _Response:
    def __init__(self, status: int, body: str):
        self.status = status
        self._body = body

    def text(self) -> str:
        return self._body


class _Page:
    """Serves registered answers per URL pattern in order, repeating the last one
    (as `responses` does); an answer is (status, body, final_url or None) or an exception."""

    def __init__(self):
        self.routes: list[tuple[re.Pattern, list]] = []
        self.calls: list[str] = []
        self.url = ""

    def add(self, pattern, body: str = "", status: int = 200, final_url: str | None = None, raises=None):
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
        self.page = _Page()
        self.closed = False
        self.kwargs = None

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def session(monkeypatch):
    s = _Session()

    def open_session():
        return s

    monkeypatch.setattr(linkedin, "_open_session", open_session)
    drain_errors()
    drain_pushback("linkedin")
    return s


@pytest.fixture(autouse=True)
def small_pages(monkeypatch):
    """The fake pages hold a few cards: any non-empty one counts as a full page, as in `_cards`."""
    monkeypatch.setattr(linkedin, "_FULL_PAGE", 1)


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    out = []

    def fake_sleep(seconds, stop=None):
        out.append(seconds)
        return stop.is_set() if stop is not None else False

    monkeypatch.setattr(linkedin, "_sleep", fake_sleep)
    return out


_PAUSE = (2.0, 4.0)


def _run(config=None, **kwargs):
    kwargs.setdefault("budget", 15)
    kwargs.setdefault("pause", _PAUSE)
    return linkedin.discover_run(config or _CONFIG, **kwargs)


def _cards(*cards) -> str:
    """A search page of cards: ``(job_id, title, company, date)``."""
    out = []
    for job_id, title, company, day in cards:
        out.append(f'''<li><div class="base-search-card" data-entity-urn="urn:li:jobPosting:{job_id}">
        <h3 class="base-search-card__title">{title}</h3><h4 class="base-search-card__subtitle">{company}</h4>
        <span class="job-search-card__location">Copenhagen</span><time datetime="{day}">x</time></div></li>''')
    return "<!DOCTYPE html>" + "".join(out)


def _search_pages(session, *pages: str):
    for body in pages:
        session.page.add(_SEARCH, body)


def _detail(session, job_id: str, apply_url: str | None = None, **kwargs):
    pattern = re.compile(re.escape(linkedin._DETAIL_URL.format(id=job_id)) + "$")
    session.page.add(pattern, _APPLY.format(url=apply_url) if apply_url else "<html>Easy Apply</html>", **kwargs)


def _searches(session) -> list[dict]:
    return [parse_qs(urlparse(u).query) for u in session.page.calls if "seeMoreJobPostings" in u]


def _details(session) -> list[str]:
    return [u.rsplit("/", 1)[-1] for u in session.page.calls if "jobPosting/" in u]


def _by_company(found: list[dict]) -> dict[str, dict]:
    return {e["company"]: e for e in found}


def _pending(company, job_ids, first_seen="2026-10-05T00:00:00+00:00"):
    return {company.lower(): {"company": company, "titles": ["Data Scientist"], "job_ids": job_ids, "first_seen": first_seen}}


# --------------------------------------------------------------------------- #
# pure helpers
# --------------------------------------------------------------------------- #

def test_the_keywords_are_quoted_and_joined_with_or():
    assert linkedin._or_groups(["lead data scientist", "head of ai"]) == ['"lead data scientist" OR "head of ai"']
    assert linkedin._or_groups(['say "hi"']) == ['"say hi"']
    assert linkedin._or_groups([]) == []


def test_a_long_query_is_split_into_a_few_or_groups():
    kws = [f"keyword number {i}" for i in range(10)]
    groups = linkedin._or_groups(kws, max_chars=80)
    assert len(groups) > 1 and all(len(g) <= 80 for g in groups)
    assert " OR ".join(g for g in groups).count('"') == 20  # every keyword is in exactly one group
    assert [k for g in groups for k in re.findall(r'"([^"]+)"', g)] == kws


def test_a_card_is_older_than_the_cutoff_by_its_day_not_its_time():
    since = datetime(2026, 10, 8, 15, 30, tzinfo=timezone.utc)
    assert linkedin._older({"posted_at": datetime(2026, 10, 7, tzinfo=timezone.utc)}, since)
    assert not linkedin._older({"posted_at": datetime(2026, 10, 8, tzinfo=timezone.utc)}, since)
    assert not linkedin._older({"posted_at": None}, since) and not linkedin._older({"posted_at": datetime(2020, 1, 1, tzinfo=timezone.utc)}, None)


# --------------------------------------------------------------------------- #
# the combined search
# --------------------------------------------------------------------------- #

def test_one_combined_boolean_search_replaces_a_search_per_keyword(session):
    _search_pages(session, _EMPTY)
    since = datetime.now(timezone.utc) - timedelta(days=3, hours=1)

    result = _run({**_CONFIG, "search_keywords": ["lead data scientist", "head of ai"]}, since=since)

    [query] = _searches(session)
    assert query["keywords"] == ['"lead data scientist" OR "head of ai"']
    assert query["sortBy"] == ["DD"] and query["f_TPR"] == ["r345600"] and query["location"] == ["Copenhagen"]
    assert query["start"] == ["0"]
    assert result["mode"] == "combined" and result["requests"] == 1 and result["pages"] == 1


def test_the_fitting_cards_are_grouped_by_employer_and_no_job_page_is_read_for_them(session):
    _search_pages(session, _fx("search_results.html"), _EMPTY)

    result = _run()

    assert [e["company"] for e in result["employers"]] == ["Acme Defence Systems", "Globex", "Initech"]
    globex = _by_company(result["employers"])["Globex"]
    assert globex["titles"] == ["Senior Data Scientist", "Junior Data Scientist"]
    assert globex["job_ids"] == ["4100000002", "4100000003"]
    assert globex["links"] == ["https://www.linkedin.com/jobs/view/4100000002"] and globex["detailed"] is False
    assert _details(session) == [] and result["details"] == 0 and result["stopped"] is None
    assert drain_errors() == {}


def test_it_pages_through_the_results_until_a_page_has_no_new_card(session):
    _search_pages(session, _fx("search_results.html"), _fx("search_results_2.html"), _fx("search_results_2.html"))

    result = _run()

    assert [q["start"][0] for q in _searches(session)] == ["0", "10", "20"]  # page 3 repeats page 2: no new card
    assert result["pages"] == 3 and result["search_complete"] is True and result["outcome"] == "ok"


def test_it_stops_paging_at_an_empty_page(session):
    _search_pages(session, _cards((1, "Data Scientist", "A", "2026-10-10")), _EMPTY)
    result = _run()
    assert len(_searches(session)) == 2 and result["search_complete"]


def test_it_stops_paging_once_a_card_is_older_than_since_and_drops_it(session):
    page = _cards((1, "Data Scientist", "New Co", "2026-10-10"), (2, "Data Scientist", "Old Co", "2026-10-01"))
    _search_pages(session, page, _cards((3, "Data Scientist", "Older Co", "2026-09-20")))

    result = _run(since=datetime(2026, 10, 5, tzinfo=timezone.utc))

    assert len(_searches(session)) == 1
    assert [e["company"] for e in result["employers"]] == ["New Co"] and result["search_complete"]


def test_the_page_budget_ends_the_search_and_says_so(session):
    for i in range(5):
        _search_pages(session, _cards((i * 10 + 1, "Data Scientist", f"Co {i}", "2026-10-10")))

    result = _run(budget=3)

    assert len(_searches(session)) == 3 and result["requests"] == 3
    assert result["search_complete"] is False and result["outcome"] == "budget" and result["stopped"] is None
    assert len(result["employers"]) == 3


def test_a_long_keyword_list_is_searched_as_several_or_groups_sharing_the_budget(session, monkeypatch):
    monkeypatch.setattr(linkedin, "_MAX_QUERY_CHARS", 40)
    _search_pages(session, _cards((1, "Data Scientist", "A", "2026-10-10")), _EMPTY, _cards((2, "Data Scientist", "B", "2026-10-10")), _EMPTY)

    result = _run({**_CONFIG, "search_keywords": ["data scientist", "ml engineer", "data analyst"]})

    queries = [q["keywords"][0] for q in _searches(session)]
    assert len(set(queries)) == 2 and all(" OR " in q or q.count('"') == 2 for q in queries)
    assert [e["company"] for e in result["employers"]] == ["A", "B"]


def test_only_titles_on_topic_for_the_keywords_are_kept(session):
    _search_pages(session, _fx("search_results.html"), _EMPTY)
    result = _run({**_CONFIG, "search_keywords": ["advanced analytics lead"]})
    assert [e["company"] for e in result["employers"]] == ["Acme Defence Systems"]
    assert result["employers"][0]["job_ids"] == ["4100000001"]


def test_a_loose_title_counts_as_on_topic(session):
    _search_pages(session, _fx("search_results.html"), _EMPTY)
    result = _run({**_CONFIG, "search_keywords": ["senior data scientist"]})
    assert {e["company"] for e in result["employers"]} == {"Acme Defence Systems", "Globex", "Initech"}


def test_the_profiles_topic_terms_decide_which_titles_are_on_topic(session):
    _search_pages(session, _fx("search_results.html"), _EMPTY)
    result = _run({**_CONFIG, "search_keywords": ["advanced analytics lead"], "topic_terms": ["data scientist"]})
    assert {e["company"] for e in result["employers"]} == {"Acme Defence Systems", "Globex", "Initech"}


def test_it_falls_back_to_role_targets(session):
    _search_pages(session, _EMPTY)
    _run({"role_targets": ["a", "b"], "location": "x"})
    assert _searches(session)[0]["keywords"] == ['"a" OR "b"']


def test_without_keywords_no_browser_is_opened(session):
    assert _run({"location": "x"})["employers"] == []
    assert session.kwargs is None


def test_a_fresh_http_session_is_used_and_closed_and_no_browser_is_needed(session, monkeypatch):
    import requests

    seen = {}

    class Http:
        headers = {}

        def get(self, url, timeout=None):
            seen["ua"] = self.headers["User-Agent"]
            return type("R", (), {"status_code": 200, "url": url, "text": _EMPTY})()

        def close(self):
            seen["closed"] = True

    monkeypatch.undo()  # the autouse fakes: use the real `_open_session` on a stub `requests.Session`
    monkeypatch.setattr(requests, "Session", Http)
    http = linkedin._open_session()
    assert http.page.goto("https://x/y").text() == _EMPTY
    http.close()
    assert seen["ua"] == http_client.USER_AGENT and seen["closed"]


# --------------------------------------------------------------------------- #
# job pages: only for employers follow could not resolve by name
# --------------------------------------------------------------------------- #

def test_job_pages_are_read_for_pending_employers_oldest_first_within_the_budget(session):
    _search_pages(session, _EMPTY)
    _detail(session, "9001", "https://careers.oldco.com/1")
    _detail(session, "9002")
    pending = {**_pending("Globex", ["4400000001"], "2026-10-05T00:00:00+00:00"),
               **_pending("OldCo", ["9001"], "2026-10-01T00:00:00+00:00"),
               **_pending("Third", ["9003"], "2026-10-07T00:00:00+00:00")}
    pending["globex"]["job_ids"] = ["9002"]

    result = _run(pending=pending, budget=3)  # one search + two job pages

    assert _details(session) == ["9001", "9002"]
    by = _by_company(result["employers"])
    assert by["OldCo"]["detailed"] and by["OldCo"]["links"][0] == "https://careers.oldco.com/1"
    assert by["Globex"]["detailed"] and by["Globex"]["links"] == ["https://www.linkedin.com/jobs/view/9002"]  # Easy Apply
    assert not by["Third"]["detailed"] and result["details"] == 2 and result["outcome"] == "budget"


def test_a_pending_employer_merges_with_its_new_cards_and_is_read_on_the_newest(session):
    _search_pages(session, _fx("search_results.html"), _EMPTY)
    _detail(session, "4100000002", "https://globex.pinpointhq.com/en/postings/abc")
    result = _run(pending=_pending("Globex", ["4400000001"]))

    by = _by_company(result["employers"])
    assert _details(session) == ["4100000002"]
    assert by["Globex"]["job_ids"] == ["4400000001", "4100000002", "4100000003"] and by["Globex"]["first_seen"] == "2026-10-05T00:00:00+00:00"
    assert by["Globex"]["links"][0] == "https://globex.pinpointhq.com/en/postings/abc"
    assert not by["Acme Defence Systems"]["detailed"] and by["Acme Defence Systems"]["first_seen"]  # new cards are stamped


def test_a_known_pending_employer_is_not_read(session):
    _search_pages(session, _EMPTY)
    result = _run(pending=_pending("Globex", ["1"]), known_companies=frozenset({"globex"}))
    assert _details(session) == [] and not result["employers"][0]["detailed"]


def test_search_leaves_room_for_a_few_job_pages(session, monkeypatch):
    monkeypatch.setattr(linkedin, "_JOB_PAGE_RESERVE", 2)
    for i in range(6):
        _search_pages(session, _cards((i * 10 + 1, "Data Scientist", f"Co {i}", "2026-10-10")))
    _detail(session, "9001")
    _detail(session, "9002")

    result = _run(pending={**_pending("A", ["9001"]), **_pending("B", ["9002"], "2026-10-06T00:00:00+00:00")}, budget=5)

    assert len(_searches(session)) == 3 and _details(session) == ["9001", "9002"] and result["requests"] == 5


# --------------------------------------------------------------------------- #
# pace
# --------------------------------------------------------------------------- #

def test_it_pauses_between_requests_not_before_the_first(session, sleeps):
    _search_pages(session, _cards((1, "Data Scientist", "A", "2026-10-10")), _EMPTY)
    _detail(session, "9001")
    _run(pending=_pending("Z", ["9001"]))
    assert len(session.page.calls) == 3 and len(sleeps) == 2
    assert all(_PAUSE[0] <= s <= _PAUSE[1] for s in sleeps)


def test_the_pause_given_is_the_pause_used(session, sleeps):
    _search_pages(session, _cards((1, "Data Scientist", "A", "2026-10-10")), _EMPTY)
    result = _run(pause=(240.0, 480.0))
    assert all(240 <= s <= 480 for s in sleeps) and result["pause"] == [240.0, 480.0]


def test_progress_is_reported_per_request_and_per_wait(session):
    from door.core import progress

    events = []

    class Rec:
        def report(self, event):
            events.append(event)

    _search_pages(session, _cards((1, "Data Scientist", "A", "2026-10-10")), _EMPTY)
    with progress.activate(Rec()):
        _run(budget=9)

    pages = [(e.message, e.done, e.total) for e in events if e.stage == "li_request"]
    assert pages == [("page 1/9", 1, 9), ("page 2/9", 2, 9)]
    waits = [e for e in events if e.stage == "li_wait"]
    assert len(waits) == 1 and waits[0].message.startswith("waiting ") and 2 <= waits[0].done <= 4


def test_a_stop_signal_ends_the_run_before_the_next_request(session):
    stop = threading.Event()
    _search_pages(session, _cards((1, "Data Scientist", "A", "2026-10-10")), _cards((2, "Data Scientist", "B", "2026-10-10")))
    goto = session.page.goto

    def goto_then_stop(url, **kwargs):
        response = goto(url, **kwargs)
        stop.set()
        return response

    session.page.goto = goto_then_stop
    result = _run(stop=stop)
    assert len(session.page.calls) == 1 and result["stopped"] == "cancelled" and not result["pushback"]
    assert [e["company"] for e in result["employers"]] == ["A"]


# --------------------------------------------------------------------------- #
# stops
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("status", [429, 999, 403, 500])
def test_it_stops_on_pushback_and_keeps_what_it_has(session, status):
    _search_pages(session, _fx("search_results.html"))
    session.page.add(_SEARCH, status=status)

    result = _run()

    assert [e["company"] for e in result["employers"]] == ["Acme Defence Systems", "Globex", "Initech"]
    assert result["stopped"] and result["pushback"] == (status != 500)
    assert result["outcome"] == ("refused" if status != 500 else "error")
    assert "linkedin" in drain_errors() and session.closed
    assert drain_pushback("linkedin") == (status != 500)


def test_a_second_429_in_a_row_stops_and_says_after_how_many_requests_and_seconds(session, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(linkedin, "_now", lambda: now[0])
    monkeypatch.setattr(linkedin, "_sleep", lambda seconds, stop=None: now.__setitem__(0, now[0] + seconds) or False)
    _search_pages(session, _cards((1, "Data Scientist", "A", "2026-10-10")))
    session.page.add(_SEARCH, status=429)

    result = _run(pause=(700.0, 700.0))

    # request 1 ok; 700 s pause; request 2 is a 429, 90 s back-off; request 3 is a 429 again: stop
    assert len(session.page.calls) == 3 and result["stopped"] == "HTTP 429"
    assert result["first_429"] == {"after_requests": 1, "after_s": 700}
    assert result["requests"] == 3 and result["outcome"] == "refused"


def test_one_429_is_waited_out_and_the_request_tried_again(session, sleeps):
    session.page.add(_SEARCH, status=429)
    _search_pages(session, _cards((1, "Data Scientist", "A", "2026-10-10")), _EMPTY)

    result = _run()

    assert [e["company"] for e in result["employers"]] == ["A"]
    assert linkedin._BACKOFF_S in sleeps and result["stopped"] is None and result["outcome"] == "ok"
    assert result["first_429"] == {"after_requests": 0, "after_s": result["first_429"]["after_s"]}
    assert len(session.page.calls) == 3 and drain_pushback("linkedin") is False


def test_a_run_without_a_refusal_has_no_first_429(session):
    _search_pages(session, _EMPTY)
    assert _run()["first_429"] is None


@pytest.mark.parametrize("failure", [{"status": 502}, {"raises": TimeoutError("Timeout 30000ms exceeded")}])
def test_one_transient_error_is_retried_once_and_counts_as_a_request(session, failure):
    session.page.add(_SEARCH, **failure)
    _search_pages(session, _fx("search_results.html"), _EMPTY)
    result = _run()
    assert len(result["employers"]) == 3 and result["requests"] == 3 and drain_errors() == {}


def test_it_stops_on_a_redirect_to_the_authwall(session):
    session.page.add(_SEARCH, "<html>Sign in</html>", final_url="https://www.linkedin.com/authwall?trk=x")
    result = _run()
    assert result["employers"] == [] and "authwall" in " ".join(drain_errors()["linkedin"])
    assert len(session.page.calls) == 1 and drain_pushback("linkedin") and result["outcome"] == "refused"


def test_a_browser_that_cannot_start_is_recorded_not_raised(monkeypatch):
    def broken():
        raise RuntimeError("Executable doesn't exist")

    monkeypatch.setattr(linkedin, "_open_session", broken)
    result = _run(pending=_pending("Globex", ["1"]))
    assert "Executable" in result["stopped"] and result["requests"] == 0 and result["outcome"] == "error"
    assert [e["company"] for e in result["employers"]] == ["Globex"]  # pending employers are never lost
    assert "Executable" in " ".join(drain_errors()["linkedin"])


def test_a_stop_during_the_job_pages_keeps_the_search_and_the_pages_already_read(session):
    _search_pages(session, _EMPTY)
    _detail(session, "9001", "https://careers.a.com/1")
    _detail(session, "9002", status=429)
    result = _run(pending={**_pending("A", ["9001"]), **_pending("B", ["9002"], "2026-10-06T00:00:00+00:00")})
    by = _by_company(result["employers"])
    assert by["A"]["detailed"] and not by["B"]["detailed"] and result["pushback"]


# --------------------------------------------------------------------------- #
# the fallback: a few keywords a run
# --------------------------------------------------------------------------- #

_ROT = ["data scientist", "ml engineer", "head of ai"]


def test_an_empty_combined_search_is_checked_with_one_keyword_and_switches_to_rotation_when_that_works(session):
    session.page.add(_SEARCH, _EMPTY)  # the combined query
    session.page.add(_SEARCH, _cards((1, "Data Scientist", "A", "2026-10-10")))  # the first keyword alone
    session.page.add(_SEARCH, _EMPTY)

    result = _run({**_CONFIG, "search_keywords": _ROT}, rotation=_ROT[:2], keyword_since={})

    qs = [q["keywords"][0] for q in _searches(session)]
    assert qs[0].count(" OR ") == 2 and qs[1] == '"data scientist"'
    assert result["mode"] == "rotate" and result["mode_switched"] is True
    assert result["searched"] == ["data scientist", "ml engineer"]
    assert [e["company"] for e in result["employers"]] == ["A"]


def test_an_empty_combined_search_stays_combined_when_the_keyword_is_empty_too(session):
    _search_pages(session, _EMPTY)
    result = _run({**_CONFIG, "search_keywords": _ROT}, rotation=_ROT[:2], keyword_since={})
    assert len(_searches(session)) == 2 and result["mode"] == "combined" and not result["mode_switched"]
    assert result["search_complete"] is True


def test_rotate_mode_searches_only_the_rotation_keywords_each_back_to_its_own_cutoff(session):
    _search_pages(session, _EMPTY)
    now = datetime.now(timezone.utc)
    result = _run({**_CONFIG, "search_keywords": _ROT}, mode="rotate", rotation=["ml engineer", "head of ai"],
                  keyword_since={"ml engineer": now - timedelta(days=2, hours=1), "head of ai": None})

    queries = _searches(session)
    assert [q["keywords"][0] for q in queries] == ['"ml engineer"', '"head of ai"']
    assert queries[0]["f_TPR"] == ["r259200"] and "f_TPR" not in queries[1]
    assert result["mode"] == "rotate" and result["searched"] == ["ml engineer", "head of ai"]


def test_rotate_mode_keeps_the_title_gate_of_all_keywords(session):
    _search_pages(session, _cards((1, "Data Scientist", "A", "2026-10-10"), (2, "Plumber", "B", "2026-10-10")), _EMPTY)
    result = _run({**_CONFIG, "search_keywords": _ROT}, mode="rotate", rotation=["ml engineer"], keyword_since={})
    assert [e["company"] for e in result["employers"]] == ["A"]


def test_rotate_mode_pages_a_keyword_to_its_end_even_when_a_page_repeats_earlier_cards(session):
    """Cards the first keyword listed do not end the second keyword's paging: its next page may be new."""
    a, b, c = (1, "Data Scientist", "A", "2026-10-10"), (2, "Data Scientist", "B", "2026-10-10"), (3, "Data Scientist", "C", "2026-10-10")
    session.page.add(_SEARCH, _cards(a))     # keyword 1, page 1
    session.page.add(_SEARCH, _EMPTY)        # keyword 1 ends
    session.page.add(_SEARCH, _cards(a))     # keyword 2, page 1: all seen
    session.page.add(_SEARCH, _cards(b, c))  # keyword 2, page 2: new
    session.page.add(_SEARCH, _EMPTY)

    result = _run({**_CONFIG, "search_keywords": _ROT}, mode="rotate", rotation=["data scientist", "ml engineer"],
                  keyword_since={})

    assert [e["company"] for e in result["employers"]] == ["A", "B", "C"]
    assert result["searched"] == ["data scientist", "ml engineer"]


def test_a_short_page_is_the_last_one_and_no_empty_page_is_requested(session, monkeypatch):
    monkeypatch.setattr(linkedin, "_FULL_PAGE", 2)
    _search_pages(session, _cards((1, "Data Scientist", "A", "2026-10-10")))
    result = _run({**_CONFIG, "search_keywords": _ROT}, mode="rotate", rotation=["data scientist"], keyword_since={})
    assert len(_searches(session)) == 1 and result["search_complete"] is True


@pytest.mark.parametrize("wall", [
    "<html><head><title>Just a moment...</title></head><body></body></html>",
    "<html><body><form action='/uas/login-submit'><input type='password' name='session_password'></form></body></html>",
])
def test_a_wall_page_instead_of_the_results_stops_as_a_refusal_not_as_no_employers(session, wall):
    """A wall served without a redirect is a refusal too (#19), never "no employers"."""
    _search_pages(session, wall)
    result = _run()
    assert result["outcome"] == "refused" and result["pushback"] and "instead of the results" in result["stopped"]
    assert drain_pushback("linkedin") is True


def test_linkedins_empty_answer_is_no_wall(session):
    _search_pages(session, _EMPTY)
    result = _run()
    assert result["outcome"] == "ok" and not result["pushback"]


def test_a_block_page_sent_with_a_server_error_is_a_refusal_not_a_failing_server(session):
    session.page.add(_SEARCH, "<html><head><title>The URL you requested has been blocked</title></head></html>", status=500)
    result = _run()
    assert result["outcome"] == "refused" and result["pushback"] and len(session.page.calls) == 1
    assert drain_pushback("linkedin") is True
