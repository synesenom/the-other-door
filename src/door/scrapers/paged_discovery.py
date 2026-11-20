"""The shared crawl of the result-page discovery sources (HelloWork, profession.hu, Jobbsafari), read
through `sdk.paged_discovery`.

A source gives its URLs and its page reading; this module does the rest, the same for each: one search per
keyword of the rotation, at most *page_cap* pages of *full_page* ads (a short page being the last), at most
*max_budget* requests a run with at least *min_pause* seconds between two, whatever the engine hands over.
Plain HTTP, logged out, a fresh session per run. The first 429 or 403, a redirect off the listing (*is_wall*)
or a wall page (`wall_page`) where the results should be stops the run and rests the source for a day
(`record_pushback`); a 5xx or a failed load is tried once more, then stops. Nothing is read of an ad but what a
card carries.
"""

import random
import threading
import time
from datetime import datetime, timezone
from typing import Callable

import requests

from door.matching import title_fit
from door.scrapers import record_error, record_pushback, report, wall_page
from door.scrapers.http_client import USER_AGENT

_TIMEOUT_S = 30


class _Stop(Exception):
    """The source pushed back, or the run was cancelled: stop for this run.

    ``pushback`` marks a refusal (a block, a rate limit, a redirect to a login page) as opposed to a
    server that kept failing; only a refusal rests the source (`record_pushback`).
    """

    def __init__(self, reason: str, *, pushback: bool = False):
        super().__init__(reason)
        self.pushback = pushback


class _Spent(Exception):
    """The request budget is used up."""


def employers_of(cards: list[dict], config: dict) -> list[dict]:
    """The cards whose title is on topic for *config* grouped by employer (two spellings of a name are
    one), in order of first sight. ``job_ids`` stays empty: the ad is never read. Pure."""
    from door.core.employers import companies  # call-time, like sdk.name_key

    grouped: dict[str, dict] = {}
    terms = title_fit.topic_terms(config)
    for card in cards:
        if not title_fit.on_topic(card["title"], terms):
            continue
        employer = grouped.setdefault(companies.name_key(card["company"]) or card["company"].lower(), {
            "company": card["company"], "titles": [], "links": [], "job_ids": [], "detailed": False,
        })
        if card["title"] not in employer["titles"]:
            employer["titles"].append(card["title"])
        if card["url"] and card["url"] not in employer["links"]:
            employer["links"].append(card["url"])
    return list(grouped.values())


def _now() -> float:
    return time.monotonic()


def _sleep(seconds: float, stop: threading.Event | None) -> bool:
    """Wait *seconds*; True when *stop* was set meanwhile (the wait ends early)."""
    if stop is None:
        time.sleep(seconds)
        return False
    return stop.wait(seconds)


class _Crawler:
    """The requests of one run: counts them against the budget, pauses between them, and notes when
    the source first refused. Not thread-safe; one run uses it from one thread."""

    def __init__(self, session, *, name: str, is_wall: Callable[[str], bool], budget: int, pause: tuple[float, float],
                 stop: threading.Event | None):
        self.session, self.name, self.is_wall, self.budget, self.pause, self.stop = session, name, is_wall, budget, pause, stop
        self.requests = 0
        self.started = _now()
        self.first_429: dict | None = None

    def seconds(self) -> int:
        return int(round(_now() - self.started))

    def _wait(self) -> None:
        if self.requests == 0:
            return
        seconds = int(round(random.uniform(*self.pause)))
        report(f"waiting {seconds} s", seconds, site=self.name, stage="li_wait")
        if _sleep(seconds, self.stop):
            raise _Stop("cancelled")

    def get(self, url: str) -> str:
        """Load *url* and return the body. Raises `_Spent` when the budget is used up, `_Stop` on a
        stop signal or pushback. A pause comes before every load but the run's first. 429 and 403 stop
        at once; any other error status or a failed load gets one more try (also counted), then stops;
        a redirect to a login page or off the listing stops too."""
        transient = 0
        while True:
            if self.stop is not None and self.stop.is_set():
                raise _Stop("cancelled")
            if self.requests >= self.budget:
                raise _Spent()
            self._wait()
            self.requests += 1
            report(f"page {self.requests}/{self.budget}", self.requests, self.budget, site=self.name, stage="li_request")
            try:
                resp = self.session.get(url, timeout=_TIMEOUT_S)
            except Exception as exc:  # noqa: BLE001 - network errors and timeouts
                transient += 1
                if transient > 1:
                    raise _Stop(f"{type(exc).__name__}: {exc}")
                continue
            if self.is_wall(resp.url):
                raise _Stop(f"redirected away from the listing ({resp.url})", pushback=True)
            if resp.status_code in (429, 403):
                if resp.status_code == 429:
                    self.first_429 = {"after_requests": self.requests - 1, "after_s": self.seconds()}
                raise _Stop(f"HTTP {resp.status_code}", pushback=True)
            if resp.status_code >= 400 and (wall := wall_page(resp.text)):
                raise _Stop(f"HTTP {resp.status_code}: {wall} instead of the results", pushback=True)
            if resp.status_code >= 400:
                transient += 1
                if transient > 1:
                    raise _Stop(f"HTTP {resp.status_code}")
                continue
            return resp.text


def _stop(name: str, stop: _Stop) -> None:
    message = f"stopped for this run: {stop}"
    report(message, site=name)
    record_error(name, message)
    if stop.pushback:
        record_pushback(name)


def discover(
    config: dict, *, name: str, search_url: Callable[[str, int, dict], str], parse_cards: Callable[[str], list[dict]],
    is_wall: Callable[[str], bool], page_cap: int, full_page: int, max_budget: int, min_pause: tuple[float, float],
    budget: int | None = None, pause: tuple[float, float] | None = None, rotation=(),
    stop: threading.Event | None = None, **_ignored,
) -> dict:
    """One source's discovery run: its requests, and how they went. Side-effect free apart from
    `record_error`/`record_pushback` and progress events, so it can run in a worker thread.

    The source gives *search_url* (keyword, page number from 1 and config to a URL), *parse_cards* (a
    result page to ``{platform_id, title, company, location, url}`` cards), *is_wall* (a final URL that is
    not the listing) and its limits
    (*page_cap*, *full_page*, *max_budget*, *min_pause*). The *rotation* keywords are searched one at a
    time; the ones the budget did not reach are in no ``searched`` and wait for the next run. *budget* and
    *pause* are the engine's, held to the source's limits (the engine's defaults are made for LinkedIn). The
    rest of what the engine passes (``since``, ``known_companies``, ``mode``, ...) is not used: the search has
    no date filter, and an employer already known is dropped when queued.

    Returns the `sdk.DiscoveryResult` fields; ``mode`` is always ``rotate``.
    """
    budget = max(1, min(max_budget if budget is None else budget, max_budget))
    pause = (max((pause or min_pause)[0], min_pause[0]), max((pause or min_pause)[1], min_pause[1]))
    result: dict = {"employers": [], "details": 0, "pages": 0, "requests": 0, "stopped": None, "pushback": False,
                    "outcome": "ok", "mode": "rotate", "mode_switched": False, "searched": [], "search_complete": False,
                    "first_429": None, "budget": budget, "pause": [pause[0], pause[1]], "seconds": 0}
    if not title_fit.keywords(config):
        return result
    now = datetime.now(timezone.utc).isoformat()
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    crawler = _Crawler(session, name=name, is_wall=is_wall, budget=budget, pause=pause, stop=stop)
    cards: list[dict] = []
    complete = True
    try:
        try:
            seen: set[str] = set()
            for keyword in rotation:
                if not _page_through(crawler, search_url, parse_cards, page_cap, full_page, keyword, config, cards, seen):
                    complete = False
                    break
                result["searched"].append(keyword)
        except _Stop as stopped:
            complete = False
            _stop(name, stopped)
            result.update(stopped=str(stopped), pushback=stopped.pushback)
        finally:  # the cards read so far count, stopped or not
            result["employers"] = [{**e, "first_seen": now} for e in employers_of(cards, config)]
    finally:
        session.close()
    result.update(requests=crawler.requests, pages=crawler.requests, first_429=crawler.first_429,
                  seconds=crawler.seconds(), search_complete=complete)
    if result["stopped"] == "cancelled":
        result["outcome"] = "cancelled"
    elif result["stopped"]:
        result["outcome"] = "refused" if result["pushback"] else "error"
    elif not complete:
        result["outcome"] = "budget"
    return result


def _page_through(crawler, search_url, parse_cards, page_cap, full_page, keyword, config, cards, seen) -> bool:
    """Read the result pages of one *keyword* into *cards* (ads not in *seen* yet) until a short page,
    *page_cap* pages, or the budget. True when it ended by itself (not by the budget)."""
    for number in range(1, page_cap + 1):
        try:
            html = crawler.get(search_url(keyword, number, config))
        except _Spent:
            return False
        page = parse_cards(html)
        if not page and (wall := wall_page(html)):
            raise _Stop(f"{wall} instead of the results", pushback=True)
        new = [c for c in page if c["platform_id"] not in seen]
        seen.update(c["platform_id"] for c in new)
        cards.extend(new)
        if len(page) < full_page:
            return True
    return True
