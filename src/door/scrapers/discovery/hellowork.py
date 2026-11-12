#!/usr/bin/env python3
"""Employer discovery from HelloWork (France's large job board, hellowork.com), read logged out.

HelloWork is not a job source for door and not a `Site`: its terms (CGU art. 8.2, https://www.hellowork-group.com/fr/legal/cgu-hellowork/)
ban "l'utilisation de systemes automatises ou de logiciels pour extraire des donnees du Site ... a quelques
fins que ce soit, commerciales ou non" (art. 9.3 adds an extraction ban on the database), so no posting is
stored, scored or tailored from it. What it is good for is telling WHICH employers hire for the user's
keywords. `discover` reads a few search pages, keeps the employers whose ad title is on topic, and queues
them with the ad link; `follow` then looks for each employer's own feed by name (an ad link on a job board
is never an employer's careers page, `ats_detect.is_job_board`). That is the same use LinkedIn gets
(`door.scrapers.discovery.linkedin`) and profession.hu (`door.scrapers.discovery.profession`) and it stays
small and slow:

- plain HTTP, logged out: no login, no cookies kept (a fresh session per run), no account, no
  headless browser, `sdk.USER_AGENT` like every other request;
- one search per keyword of the rotation, ``/fr-fr/emploi/recherche.html?k=<keyword>&l=<city>[&p=<n>]``,
  at most `_PAGE_CAP` pages of `_FULL_PAGE` ads, a short page being the last; at most `_MAX_BUDGET`
  requests a run with at least `_MIN_PAUSE` seconds between two, whatever the engine hands over;
- the first 429 or 403, or a redirect to a login page or off the listing, stops the run and rests the
  source for a day (`record_pushback`); a 5xx or a failed load is tried once more, then stops;
- no ad text is read or kept, no job page is opened: a card gives the id, title, employer, place and
  link, and only the employer, the title and the link are handed on. The employer's own apply link sits
  behind the ad page and is not needed.

Terms (https://www.hellowork-group.com/fr/legal/cgu-hellowork/, read 2026-10-31): art. 8.2 and 9.3 as quoted above; a verdict of `unsure`.
robots.txt (checked 2026-10-31) disallows any URL with a query and ``/fr-fr/emploi/recherche.html``
for ``User-agent: *``; it is reported here and does not gate requests (`http_client.OBEY_ROBOTS`).

Markup (checked 2026-10-31): each ad is an ``li[data-id-storage-item-id]`` (the id) holding hidden
inputs ``title`` and ``company`` (the hide-offer form), the ad link ``a[data-cy=offerTitle]``
(``/fr-fr/emplois/<id>.html``, the heading ``h3`` repeating title and employer) and the place in
``[data-cy=localisationCard]`` (``"Paris 2e - 75"``). A page lists 30 ads; ``p=2`` gives the next 30.

Parsing is pure and separate from the network, so fixtures test it offline.
"""

import random
import re
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit

import requests
from bs4 import BeautifulSoup

from door.scrapers import sdk

_SITE = "hellowork"

# The discovery-source contract (`door.core.discovery_sources`).
NAME = "hellowork"
COUNTRIES: tuple[str, ...] = ("fr",)
CONFIG_KEY = "hellowork_discovery"
LABEL = "HelloWork"  # how the engine names it in a skip reason
VERDICT = "unsure"  # the terms forbid automated access: runs only once the user turned it on
TERMS_URL = "https://www.hellowork-group.com/fr/legal/cgu-hellowork/"
TERMS_SUMMARY = "its terms (CGU art. 8.2 and 9.3) ban automated systems and software that extract data from the site"

_HOST = "www.hellowork.com"
_BASE = "https://" + _HOST
_PAGE_CAP = 3  # pages read for one keyword
_FULL_PAGE = 30  # ads a full result page lists; a page with fewer is the last one
_MAX_BUDGET = 30  # requests a run, whatever the engine allows
_MIN_PAUSE = (3.0, 6.0)  # seconds between two requests, at least
_TIMEOUT_S = 30
_LISTING_PATH = re.compile(r"^/fr-fr/emplois?(/|\.|$)")  # where a search or an ad lives; anything else is a wall


class _Stop(Exception):
    """HelloWork pushed back, or the run was cancelled: stop for this run.

    ``pushback`` marks a refusal (a block, a rate limit, a redirect to a login page) as opposed to a
    server that kept failing; only a refusal rests the source (`record_pushback`).
    """

    def __init__(self, reason: str, *, pushback: bool = False):
        super().__init__(reason)
        self.pushback = pushback


class _Spent(Exception):
    """The request budget is used up."""


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #

def _collapse(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _city(location: str) -> str:
    """The city of a profile's `location` (``"Paris, France"`` gives ``"Paris"``). Pure."""
    return _collapse((location or "").split(",")[0])


def _search_url(keyword: str, city: str, page: int) -> str:
    query = {"k": keyword.strip()}
    if city:
        query["l"] = city
    if page > 1:
        query["p"] = str(page)
    return f"{_BASE}/fr-fr/emploi/recherche.html?{urlencode(query)}"


def _is_wall(url: str) -> bool:
    """Whether a final URL is not a listing or an ad of HelloWork (a login page, another host). Pure."""
    parts = urlsplit(url)
    return parts.netloc != _HOST or not _LISTING_PATH.match(parts.path)


def _parse_cards(html: str) -> list[dict]:
    """The ads of a result page as ``{platform_id, title, company, location, url}``, in page order. An ad
    listed twice counts once; one without an id, a title or an employer is skipped. The URL has no query. Pure."""
    cards: list[dict] = []
    seen: set[str] = set()
    for item in BeautifulSoup(html, "html.parser").select("li[data-id-storage-item-id]"):
        platform_id = _collapse(item.get("data-id-storage-item-id"))
        title_input = item.select_one('input[name="title"]')
        company_input = item.select_one('input[name="company"]')
        spans = item.select("h3 span")
        title = _collapse(title_input.get("value") if title_input is not None else spans[0].get_text() if spans else "")
        company = _collapse(company_input.get("value") if company_input is not None else spans[1].get_text() if len(spans) > 1 else "")
        if not platform_id or not title or not company or platform_id in seen:
            continue
        seen.add(platform_id)
        place = item.select_one('[data-cy="localisationCard"]')
        anchor = item.select_one('a[data-cy="offerTitle"]')
        path = urlsplit(anchor.get("href") or "").path if anchor is not None else ""
        cards.append({
            "platform_id": platform_id, "title": title, "company": company,
            "location": _collapse(place.get_text()) if place is not None else "",
            "url": f"{_BASE}{path}" if path.startswith("/") else "",
        })
    return cards


def _employers(cards: list[dict], config: dict) -> list[dict]:
    """The cards whose title is on topic for *config* grouped by employer (two spellings of a name are
    one), in order of first sight. ``job_ids`` stays empty: the ad is never read. Pure."""
    grouped: dict[str, dict] = {}
    terms = sdk.topic_terms(config)
    for card in cards:
        if not sdk.on_topic(card["title"], terms):
            continue
        employer = grouped.setdefault(sdk.name_key(card["company"]) or card["company"].lower(), {
            "company": card["company"], "titles": [], "links": [], "job_ids": [], "detailed": False,
        })
        if card["title"] not in employer["titles"]:
            employer["titles"].append(card["title"])
        if card["url"] and card["url"] not in employer["links"]:
            employer["links"].append(card["url"])
    return list(grouped.values())


# --------------------------------------------------------------------------- #
# Network
# --------------------------------------------------------------------------- #

class _Response:
    def __init__(self, resp: requests.Response):
        self.status = resp.status_code
        self.url = resp.url
        self._text = resp.text

    def text(self) -> str:
        return self._text


class _HttpSession:
    """A fresh logged-out HTTP session: no saved cookies, `http_client.USER_AGENT`. `page` is itself
    (``goto``, ``url``)."""

    def __init__(self):
        self._http = requests.Session()
        self._http.headers["User-Agent"] = sdk.USER_AGENT
        self.page = self
        self.url = ""

    def goto(self, url: str, **_kwargs) -> _Response:
        resp = self._http.get(url, timeout=_TIMEOUT_S)
        self.url = resp.url
        return _Response(resp)

    def close(self) -> None:
        self._http.close()


def _open_session() -> _HttpSession:
    return _HttpSession()


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
    HelloWork first refused. Not thread-safe; one run uses it from one thread."""

    def __init__(self, page, *, budget: int, pause: tuple[float, float], stop: threading.Event | None):
        self.page, self.budget, self.pause, self.stop = page, budget, pause, stop
        self.requests = 0
        self.started = _now()
        self.first_429: dict | None = None

    def seconds(self) -> int:
        return int(round(_now() - self.started))

    def _wait(self) -> None:
        if self.requests == 0:
            return
        seconds = int(round(random.uniform(*self.pause)))
        sdk.report(f"waiting {seconds} s", seconds, site=_SITE, stage="li_wait")
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
            sdk.report(f"page {self.requests}/{self.budget}", self.requests, self.budget, site=_SITE, stage="li_request")
            try:
                resp = self.page.goto(url)
            except Exception as exc:  # noqa: BLE001 - network errors and timeouts
                transient += 1
                if transient > 1:
                    raise _Stop(f"{type(exc).__name__}: {exc}")
                continue
            if _is_wall(self.page.url):
                raise _Stop(f"redirected away from the listing ({self.page.url})", pushback=True)
            if resp.status in (429, 403):
                if resp.status == 429:
                    self.first_429 = {"after_requests": self.requests - 1, "after_s": self.seconds()}
                raise _Stop(f"HTTP {resp.status}", pushback=True)
            if resp.status >= 400:
                transient += 1
                if transient > 1:
                    raise _Stop(f"HTTP {resp.status}")
                continue
            return resp.text()


def _stop(stop: _Stop) -> None:
    message = f"stopped for this run: {stop}"
    sdk.report(message, site=_SITE)
    sdk.record_error(_SITE, message)
    if stop.pushback:
        sdk.record_pushback(_SITE)


def _page_through(crawler: _Crawler, keyword: str, city: str, cards: list[dict], seen: set[str]) -> bool:
    """Read the result pages of one *keyword* into *cards* (ads not in *seen* yet) until a short page,
    `_PAGE_CAP` pages, or the budget. True when it ended by itself (not by the budget)."""
    for number in range(1, _PAGE_CAP + 1):
        try:
            html = crawler.get(_search_url(keyword, city, number))
        except _Spent:
            return False
        page = _parse_cards(html)
        new = [c for c in page if c["platform_id"] not in seen]
        seen.update(c["platform_id"] for c in new)
        cards.extend(new)
        if len(page) < _FULL_PAGE:
            return True
    return True


def discover_run(
    config: dict, *, budget: int = _MAX_BUDGET, pause: tuple[float, float] = _MIN_PAUSE, rotation=(),
    stop: threading.Event | None = None, **_ignored,
) -> dict:
    """One discovery run's requests, and how they went. Side-effect free apart from
    `record_error`/`record_pushback` and progress events, so it can run in a worker thread.

    The *rotation* keywords are searched one at a time; the ones the budget did not reach are in no
    ``searched`` and wait for the next run. *budget* and *pause* are the engine's, held to
    `_MAX_BUDGET` and `_MIN_PAUSE` (the engine's defaults are made for LinkedIn). The rest of what the
    engine passes (``since``, ``known_companies``, ``mode``, ...) is not used: the search has no date
    filter, and an employer already known is dropped when queued.

    Returns the `sdk.DiscoveryResult` fields; ``mode`` is always ``rotate``.
    """
    budget = max(1, min(budget, _MAX_BUDGET))
    pause = (max(pause[0], _MIN_PAUSE[0]), max(pause[1], _MIN_PAUSE[1]))
    result: dict = {"employers": [], "details": 0, "pages": 0, "requests": 0, "stopped": None, "pushback": False,
                    "outcome": "ok", "mode": "rotate", "mode_switched": False, "searched": [], "search_complete": False,
                    "first_429": None, "budget": budget, "pause": [pause[0], pause[1]], "seconds": 0}
    if not sdk.keywords(config):
        return result
    now = datetime.now(timezone.utc).isoformat()
    try:
        session = _open_session()
    except Exception as exc:  # noqa: BLE001
        stopped = _Stop(f"the HTTP session did not start: {exc}")
        _stop(stopped)
        result.update(stopped=str(stopped), outcome="error")
        return result
    crawler = _Crawler(session.page, budget=budget, pause=pause, stop=stop)
    cards: list[dict] = []
    complete = True
    try:
        try:
            seen: set[str] = set()
            for keyword in rotation:
                if not _page_through(crawler, keyword, _city(config.get("location") or ""), cards, seen):
                    complete = False
                    break
                result["searched"].append(keyword)
        except _Stop as stopped:
            complete = False
            _stop(stopped)
            result.update(stopped=str(stopped), pushback=stopped.pushback)
        finally:  # the cards read so far count, stopped or not
            result["employers"] = [{**e, "first_seen": now} for e in _employers(cards, config)]
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


# --- the discovery-source contract ----------------------------------------------------------

def run(config: dict, **kwargs) -> "sdk.DiscoveryResult":
    """`discover_run`, looked up at call time (a test replaces it)."""
    return discover_run(config, **kwargs)
