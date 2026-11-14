#!/usr/bin/env python3
"""Employer discovery from LinkedIn Jobs (linkedin.com), read logged out.

LinkedIn is not a job source for door. What it is good for is telling WHICH employers hire for
the user's keywords: `discover` reads the search cards (job id, title, company, location, date; a
card has no description), `follow` tries each employer by name, and only for the ones it cannot
resolve does `discover` read one job page, for the apply link, which usually names the employer's
own job system. Easy Apply jobs (LinkedIn-only, no offsite link) are not covered.

Uses the public guest endpoints behind LinkedIn's logged-out job search, the way the open-source
JobSpy project (MIT) does: no login, no cookies kept, no account, and no browser. They answer a
plain HTTP client (checked live 2026-10-14: 134 requests at a
2-4 s pace read every posting of 13 keywords for a week, one 429 cleared after 90 s).

1. Search: ``/jobs-guest/jobs/api/seeMoreJobPostings/search`` with ``location``, ``sortBy=DD``,
   ``f_TPR=r<seconds>`` from the cutoff and ``start`` (10 cards a page, newest first; the
   results end by themselves, a short page being the last). The default ``rotate`` mode searches
   the keywords one at a time, each quoted, each paged to its end, and the employers of all of
   them are the union: one boolean ``"a" OR "b"`` query (``combined`` mode) returns fewer cards
   than its first keyword does alone, so it loses employers. Each card gives the job id
   (``data-entity-urn``), title, company, location and date.
2. Detail, only for the *pending* employers (the ones follow could not resolve by name):
   ``/jobs-guest/jobs/api/jobPosting/<id>`` for where the apply button leads.

Terms: https://www.linkedin.com/legal/user-agreement - they ask for no scrapers; robots.txt
disallows both paths. This module is not a `Site`. It is small and slow: the caller gives the
request ``budget`` of a run (search pages and job pages together, adapting to what LinkedIn
tolerated before: `door.core.discovery_state`) and the ``pause`` between two requests (2 to 4 s
by default), details only for titles on topic for the keywords (`door.matching.title_fit.on_topic`).
LinkedIn limits a burst of about a hundred requests with HTTP 429; the first 429 of a run is waited
out (`_BACKOFF_S`) and the request tried again, a second one in a row stops the run, as does any
other 4xx/5xx after one retry, a redirect to a login or authwall page, or a wall page (a captcha,
a consent page, `sdk.wall_page`) where the results should be. A refusal is reported
with `record_pushback`; the caller rests discovery for a day. A ``stop`` event ends the run at
the next request, so it can run in a worker thread beside the other steps.

Parsing is pure and separate from the network so fixtures test it offline.
"""

import json
import random
import re
import threading
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from bs4 import BeautifulSoup

from door.scrapers import sdk

_SITE = "linkedin"

# The discovery-source contract (`door.core.discovery_sources`).
NAME = "linkedin"
COUNTRIES: tuple[str, ...] = ()  # works anywhere
CONFIG_KEY = "linkedin_discovery"
LABEL = "LinkedIn"  # how the engine names it in a skip reason
VERDICT = "unsure"  # the terms forbid automated access: runs only once the user turned it on
TERMS_URL = "https://www.linkedin.com/legal/user-agreement"
TERMS_SUMMARY = "its user agreement asks for no scrapers or other automated access"
_BASE = "https://www.linkedin.com"
_SEARCH_URL = _BASE + "/jobs-guest/jobs/api/seeMoreJobPostings/search"
_DETAIL_URL = _BASE + "/jobs-guest/jobs/api/jobPosting/{id}"
_VIEW_URL = _BASE + "/jobs/view/{id}"

# The budget and the pause of a run come from the caller (`discovery_state.pace`); these are the
# query's own limits. LinkedIn answered 429 after 107 and 133 requests at a 2-4 s pace (2026-10-14)
# and the next request, 90 s later, went through.
_MAX_QUERY_CHARS = 700  # a combined query longer than this is split into OR groups
_JOB_PAGE_RESERVE = 3  # requests kept back from the search for the job pages of pending employers
_PAGE_SIZE = 10  # the offset step between two search pages
_FULL_PAGE = 10  # cards a full search page lists; a page with fewer is the last one

_WALL_PATH = re.compile(r"/(authwall|login|uas/login|checkpoint)\b")
_STOP_STATUSES = (429, 999)  # never retried
_TIMEOUT_S = 30
_BACKOFF_S = 90  # wait after a first 429 before the one retry
_MAX_START = 990  # LinkedIn lists no result past this offset


class _Stop(Exception):
    """LinkedIn pushed back: stop the site for this run.

    ``pushback`` marks a refusal (a block, a rate limit, a login wall) as opposed
    to a server that kept failing; only a refusal rests the site (`record_pushback`).
    """

    def __init__(self, reason: str, *, pushback: bool = False):
        super().__init__(reason)
        self.pushback = pushback


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #

def _collapse(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _time_filter_days(since: datetime | None, now: datetime) -> int | None:
    """The whole days back `since` reaches (at least 1); None without a cutoff."""
    return sdk.look_back_days(since, now)


def _search_params(keyword: str, location: str, start: int, days: int | None) -> dict:
    params: dict = {"keywords": keyword, "location": location, "start": start, "sortBy": "DD"}
    if days is not None:
        params["f_TPR"] = f"r{days * 86400}"
    return params


def _quote(keyword: str) -> str:
    return '"' + keyword.replace('"', "").strip() + '"'


def _or_groups(keywords: list[str], max_chars: int | None = None) -> list[str]:
    """The keywords quoted and joined with `` OR `` into boolean queries, in order, none longer than
    *max_chars* (`_MAX_QUERY_CHARS`) unless one keyword alone is. Pure."""
    limit = _MAX_QUERY_CHARS if max_chars is None else max_chars
    groups: list[str] = []
    for keyword in keywords:
        term = _quote(keyword)
        if len(term) <= 2:
            continue
        if groups and len(groups[-1]) + len(" OR ") + len(term) <= limit:
            groups[-1] += " OR " + term
        else:
            groups.append(term)
    return groups


def _older(card: dict, since: datetime | None) -> bool:
    """Whether the card was posted on a day before *since*'s day (a card carries a date, not a time). Pure."""
    posted = card.get("posted_at")
    return since is not None and posted is not None and posted.date() < since.date()


def _is_wall(url: str) -> bool:
    """Whether *url* is LinkedIn's login or authwall page."""
    return bool(_WALL_PATH.search(urlparse(url).path))


def _card_date(card) -> datetime | None:
    tag = card.find("time")
    value = tag.get("datetime") if tag is not None else None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc) if value else None
    except ValueError:
        return None


def _parse_cards(html: str) -> list[dict]:
    """Search-page cards as dicts: platform_id, title, company, location, posted_at, url.

    A card with no job id (``data-entity-urn="urn:li:jobPosting:<id>"``) or no title is
    skipped. Pure.
    """
    soup = BeautifulSoup(html, "html.parser")
    cards: list[dict] = []
    for card in soup.find_all(class_="base-search-card"):
        platform_id = (card.get("data-entity-urn") or "").rsplit(":", 1)[-1]
        title_tag = card.find(class_="base-search-card__title")
        title = _collapse(title_tag.get_text()) if title_tag is not None else ""
        if not platform_id.isdigit() or not title:
            continue
        company = card.find(class_="base-search-card__subtitle")
        location = card.find(class_="job-search-card__location")
        cards.append({
            "platform_id": platform_id,
            "title": title,
            "company": _collapse(company.get_text()) if company is not None else "",
            "location": _collapse(location.get_text()) if location is not None else "",
            "posted_at": _card_date(card),
            "url": _VIEW_URL.format(id=platform_id),
        })
    return cards


def _unwrap_safety_redirect(href: str) -> str:
    """The target of a ``linkedin.com/safety/go/?url=…`` link; any other URL as is. Pure."""
    parsed = urlparse(href)
    if parsed.netloc.endswith("linkedin.com") and parsed.path.startswith("/safety/go"):
        target = parse_qs(parsed.query).get("url")
        if target:
            return target[0]
    return href


def _offsite_apply_url(soup: BeautifulSoup) -> str | None:
    """The off-LinkedIn apply URL in ``<code id="applyUrl"><!--"url"--></code>``, if the page has it."""
    code = soup.find("code", id="applyUrl")
    if code is None:
        return None
    raw = code.decode_contents().replace("<!--", "").replace("-->", "").strip()
    try:
        raw = json.loads(raw)
    except ValueError:
        raw = raw.strip('"')
    return _unwrap_safety_redirect(raw.replace("&amp;", "&")) if raw else None


def _parse_detail(html: str) -> dict:
    """A guest job page's ``description``, ``criteria`` (lines like "Seniority level: Associate")
    and apply route.

    ``apply_type`` is ``external`` (with ``apply_url`` when the page names it) when the
    page carries an offsite apply URL or the Apply button's offsite icon, else ``unknown``:
    the guest page does not say whether the job is an Easy Apply. Pure.
    """
    soup = BeautifulSoup(html, "html.parser")
    markup = soup.find(class_="show-more-less-html__markup")
    description = markup.get_text("\n", strip=True) if markup is not None else ""
    criteria = []
    for item in soup.find_all(class_="description__job-criteria-item"):
        name = item.find(class_="description__job-criteria-subheader")
        value = item.find(class_="description__job-criteria-text")
        if name is not None and value is not None:
            criteria.append(f"{_collapse(name.get_text())}: {_collapse(value.get_text())}")
    apply_url = _offsite_apply_url(soup)
    offsite = apply_url is not None or soup.find(class_="apply-button__offsite-apply-icon") is not None \
        or soup.find(attrs={"data-svg-class-name": "apply-button__offsite-apply-icon-svg"}) is not None
    return {
        "description": description,
        "criteria": criteria,
        "apply_type": "external" if offsite else "unknown",
        "apply_url": apply_url,
    }


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
    """A fresh logged-out HTTP session: no saved cookies, `http_client.USER_AGENT`. `page` is itself,
    shaped like the browser page the crawler was written for (``goto``, ``url``)."""

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


class _Spent(Exception):
    """The request budget (or the phase's share of it) is used up."""


class _Crawler:
    """The requests of one run: counts them against the budget, pauses between them, and notes
    when LinkedIn first refused. Not thread-safe; one run uses it from one thread."""

    def __init__(self, page, *, budget: int, pause: tuple[float, float], stop: threading.Event | None):
        self.page, self.budget, self.pause, self.stop = page, budget, pause, stop
        self.requests = 0
        self.pages = 0
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

    def get(self, url: str, params: dict | None = None, *, label: str = "page", limit: int | None = None) -> str:
        """Load *url* and return the response body.

        Raises `_Spent` when the budget (or *limit*, an absolute request count for a phase) is used
        up, `_Stop` on pushback or a stop signal. A pause comes before every load but the run's
        first. 429 and 999 stop at once; any other error status or a failed load gets one more
        try (also counted), then stops. A redirect to a login or authwall page stops too.
        """
        if params:
            url = f"{url}?{urlencode(params)}"
        return self._get(url, label, self.budget if limit is None else min(limit, self.budget))

    def _get(self, url: str, label: str, limit: int) -> str:
        last, refused, transient, rate_limited = "", False, 0, False
        while True:
            if self.stop is not None and self.stop.is_set():
                raise _Stop("cancelled")
            if self.requests >= limit:
                raise _Spent()
            self._wait()
            self.requests += 1
            self.pages += label == "page"
            sdk.report(f"{label} {self.requests}/{self.budget}", self.requests, self.budget, site=_SITE, stage="li_request")
            try:
                resp = self.page.goto(url, wait_until="domcontentloaded")
            except Exception as exc:  # noqa: BLE001 - network errors and timeouts
                last, transient = f"{type(exc).__name__}: {exc}", transient + 1
                if transient > 1:
                    raise _Stop(last)
                continue
            if _is_wall(self.page.url):
                raise _Stop(f"redirected to a login page ({urlparse(self.page.url).path})", pushback=True)
            if resp is None:
                last, transient = "no response", transient + 1
                if transient > 1:
                    raise _Stop(last)
                continue
            if resp.status in _STOP_STATUSES:
                if self.first_429 is None:
                    self.first_429 = {"after_requests": self.requests - 1, "after_s": self.seconds()}
                if rate_limited:
                    raise _Stop(f"HTTP {resp.status}", pushback=True)
                rate_limited = True
                sdk.report(f"rate limited, waiting {_BACKOFF_S} s", _BACKOFF_S, site=_SITE, stage="li_wait")
                if _sleep(_BACKOFF_S, self.stop):
                    raise _Stop("cancelled")
                continue
            if resp.status >= 400 and (wall := sdk.wall_page(resp.text())):
                raise _Stop(f"HTTP {resp.status}: {wall} instead of the results", pushback=True)
            if resp.status >= 400:
                last, refused, transient = f"HTTP {resp.status}", resp.status == 403, transient + 1
                if transient > 1:
                    raise _Stop(last, pushback=refused)
                continue
            return resp.text()


def _stop(stop: "_Stop") -> None:
    message = f"stopped for this run: {stop}"
    sdk.report(message, site=_SITE)
    sdk.record_error(_SITE, message)
    if stop.pushback:
        sdk.record_pushback(_SITE)


def _employers(cards: list[dict], config: dict) -> list[dict]:
    """The cards whose title is on topic for *config* (`title_fit.topic_terms`) grouped by employer (case-insensitive), in order of first sight. Pure."""
    grouped: dict[str, dict] = {}
    terms = sdk.topic_terms(config)
    for card in cards:
        if not card["company"] or not sdk.on_topic(card["title"], terms):
            continue
        employer = grouped.setdefault(card["company"].lower(), {
            "company": card["company"], "titles": [], "links": [], "job_ids": [], "detailed": False,
        })
        employer["titles"].append(card["title"])
        employer["job_ids"].append(card["platform_id"])
    return list(grouped.values())


def _merge_pending(employers: list[dict], pending: dict, now: str) -> list[dict]:
    """*employers* (from this run's cards) merged with the *pending* ones from earlier runs.

    Pending employers come first, oldest first; an employer in both keeps its ``first_seen``
    and the ids and titles of both. Each gets ``first_seen`` and the job id to read
    (``detail_id``: the newest card of this run, else the newest pending one). Pure.
    """
    fresh = {e["company"].lower(): e for e in employers}
    merged: list[dict] = []
    for key, old in sorted(pending.items(), key=lambda kv: kv[1].get("first_seen") or ""):
        new = fresh.pop(key, None)
        employer = {"company": old["company"], "titles": list(old["titles"]), "job_ids": list(old["job_ids"]),
                    "links": [], "detailed": False, "first_seen": old.get("first_seen") or now,
                    "detail_id": (new["job_ids"][0] if new else old["job_ids"][-1]) if old["job_ids"] or new else None}
        if new:
            employer["titles"] += [t for t in new["titles"] if t not in employer["titles"]]
            employer["job_ids"] += [j for j in new["job_ids"] if j not in employer["job_ids"]]
        merged.append(employer)
    for employer in fresh.values():
        merged.append({**employer, "first_seen": now, "detail_id": employer["job_ids"][0]})
    return [e for e in merged if e["job_ids"]]


def _page_through(
    crawler: _Crawler, query: str, location: str, since: datetime | None, now: datetime,
    cards: list[dict], seen: set[str], limit: int, *, stop_when_seen: bool = True,
) -> tuple[bool, int]:
    """Read the newest-first result pages of one *query* into *cards* until a page lists no card, a
    short page ends the results, a card is older than *since* (it is dropped), or *limit* requests
    are used. With *stop_when_seen* a page without a card new to *seen* ends it too (the combined
    query); a single keyword goes on, since what it lists is not what the others listed.

    Returns ``(complete, first_page_cards)``: whether it ended by itself (not by the budget), and
    how many cards the first page listed.
    """
    days = _time_filter_days(since, now)
    first, start = None, 0
    while True:
        try:
            html = crawler.get(_SEARCH_URL, _search_params(query, location, start, days), limit=limit)
        except _Spent:
            return False, first or 0
        page = _parse_cards(html)
        if not page and (wall := sdk.wall_page(html)):
            raise _Stop(f"{wall} instead of the results", pushback=True)
        first = len(page) if first is None else first
        new = [c for c in page if c["platform_id"] not in seen]
        seen.update(c["platform_id"] for c in new)
        window = [c for c in new if not _older(c, since)]
        cards.extend(window)
        if not page or len(window) < len(new) or (stop_when_seen and not new):
            return True, first
        start += _PAGE_SIZE
        if len(page) < _FULL_PAGE or start > _MAX_START:
            return True, first


def _search(
    crawler: _Crawler, result: dict, cards: list[dict], *, keywords: list[str], location: str, mode: str,
    rotation: list[str], since: datetime | None, keyword_since: dict, now: datetime, limit: int,
) -> bool:
    """The search phase for the *mode*; returns whether it read everything it set out to read.
    Fills *cards* and ``result["searched"]`` (rotate: the keywords completed), may switch
    ``result["mode"]`` to ``rotate`` (see `discover_run`)."""
    seen: set[str] = set()
    complete = True

    def one_keyword(keyword: str) -> bool:
        done, _first = _page_through(crawler, '"' + keyword.replace('"', "") + '"', location,
                                     keyword_since.get(keyword.lower(), since), now, cards, seen, limit,
                                     stop_when_seen=False)
        if done:
            result["searched"].append(keyword)
        return done

    if mode == "combined":
        for i, group in enumerate(_or_groups(keywords)):
            done, first = _page_through(crawler, group, location, since, now, cards, seen, limit)
            if not done:
                return False
            if i == 0 and first == 0 and rotation:
                # Nothing for the combined query: is the form at fault? One keyword alone tells.
                probe_cards = len(cards)
                if not one_keyword(rotation[0]):
                    return False
                if len(cards) > probe_cards:
                    result.update(mode="rotate", mode_switched=True)
                    return all(one_keyword(k) for k in rotation[1:])
                result["searched"].clear()
                return True
        return True
    for keyword in rotation:
        if not one_keyword(keyword):
            complete = False
            break
    return complete


def discover_run(
    config: dict, *, since: datetime | None = None, keyword_since: dict | None = None,
    known_companies: frozenset[str] = frozenset(), pending: dict | None = None, budget: int = 15,
    pause: tuple[float, float] = (60.0, 120.0), mode: str = "combined", rotation=(),
    stop: threading.Event | None = None,
) -> dict:
    """One discovery run's requests, and how they went. Side-effect free apart from
    `record_error`/`record_pushback` and progress events, so it can run in a worker thread.

    *mode* ``rotate`` (what the pipeline passes, `discovery_state.SEARCH_MODE`): the *rotation* keywords, one quoted query each, each back to its
    own cutoff in *keyword_since* (``{keyword_lower: datetime}``, else *since*); the ones the budget
    did not reach are in no ``searched`` and wait for the next run. ``combined``: one boolean OR
    query of all the keywords, paged (see the module doc); when its first page is empty, the first
    of *rotation* is searched alone, and if that has cards the run switches to ``rotate`` mode for
    the rest of it (``mode_switched``). *budget* caps the requests (search pages and job pages together; the search
    leaves `_JOB_PAGE_RESERVE` of them for the job pages when employers are pending), *pause* is
    the (low, high) seconds between two. *pending* holds the employers an earlier run saw whose
    job page is still to be read (``{company_lower: {"company", "titles", "job_ids", "first_seen"}}``);
    they are merged in and read, oldest first, with what budget the search left. A *known*
    employer's page is never read. Cards read before a stop are never dropped.

    Returns ``{"employers": [{"company", "titles", "links", "job_ids", "detailed", "first_seen"}],
    "details", "pages", "requests", "stopped": reason | None, "pushback", "outcome" (``ok``,
    ``budget``, ``refused``, ``error``, ``cancelled``), "mode", "mode_switched", "searched",
    "search_complete", "first_429": {"after_requests", "after_s"} | None, "budget", "pause",
    "seconds"}``. ``links`` is the offsite apply URL (when a job page named one) then the LinkedIn
    job URL.
    """
    result: dict = {"employers": [], "details": 0, "pages": 0, "requests": 0, "stopped": None, "pushback": False,
                    "outcome": "ok", "mode": mode, "mode_switched": False, "searched": [], "search_complete": False,
                    "first_429": None, "budget": budget, "pause": [pause[0], pause[1]], "seconds": 0}
    keywords = sdk.keywords(config)
    if not keywords:
        return result
    pending = pending or {}
    known = {sdk.name_key(c) for c in known_companies}
    awaiting = [p for p in pending.values() if sdk.name_key(p["company"]) not in known]
    location = config.get("location", "") or ""
    now = datetime.now(timezone.utc)
    try:
        session = _open_session()
    except Exception as exc:  # noqa: BLE001
        stop_ = _Stop(f"the HTTP session did not start: {exc}")
        _stop(stop_)
        result.update(stopped=str(stop_), outcome="error", employers=_with_view_links(_merge_pending([], pending, now.isoformat())))
        return result
    crawler = _Crawler(session.page, budget=budget, pause=pause, stop=stop)
    cards: list[dict] = []
    job_pages_left = False
    try:
        employers: list[dict] = []
        try:
            try:
                search_limit = max(1, budget - min(len(awaiting), _JOB_PAGE_RESERVE))
                result["search_complete"] = _search(
                    crawler, result, cards, keywords=keywords, location=location, mode=mode,
                    rotation=list(rotation), since=since, keyword_since=keyword_since or {}, now=now, limit=search_limit)
            finally:  # the cards read so far count, stopped or not
                employers = _with_view_links(_merge_pending(_employers(cards, config), pending, now.isoformat()))
                result["employers"] = employers
            pending_keys = {sdk.name_key(p["company"]) for p in awaiting}
            todo = [e for e in employers if sdk.name_key(e["company"]) in pending_keys]
            for employer in todo:
                try:
                    html = crawler.get(_DETAIL_URL.format(id=employer["detail_id"]), label="job page")
                except _Spent:
                    job_pages_left = True
                    break
                apply_url = _parse_detail(html)["apply_url"]
                if apply_url:
                    employer["links"].insert(0, apply_url)
                employer["detailed"] = True
                result["details"] += 1
        except _Stop as stopped:
            _stop(stopped)
            result.update(stopped=str(stopped), pushback=stopped.pushback)
    finally:
        session.close()
    result.update(requests=crawler.requests, pages=crawler.pages, first_429=crawler.first_429, seconds=crawler.seconds())
    if result["stopped"] == "cancelled":
        result["outcome"] = "cancelled"
    elif result["stopped"]:
        result["outcome"] = "refused" if result["pushback"] else "error"
    elif not result["search_complete"] or job_pages_left:
        result["outcome"] = "budget"
    return result


def _with_view_links(employers: list[dict]) -> list[dict]:
    """Each employer's ``links`` starts as its newest LinkedIn job URL."""
    for employer in employers:
        employer["links"] = [_VIEW_URL.format(id=employer["detail_id"])]
    return employers


# --- the discovery-source contract ----------------------------------------------------------

def run(config: dict, **kwargs) -> "sdk.DiscoveryResult":
    """`discover_run`, looked up at call time (a test replaces it)."""
    return discover_run(config, **kwargs)


def extras(queue: dict) -> dict:
    """More arguments for `run` from the candidates *queue*: ``pending``, the queued employers
    `follow` could not resolve by name, still needing their job page read."""
    return {"pending": {e["name"].lower(): {"company": e["name"], "titles": e.get("titles") or [],
                                            "job_ids": e.get("job_ids") or [], "first_seen": e.get("first_seen")}
                        for e in queue.values() if sdk.awaiting_job_page(e) and e.get("job_ids")}}


def skip_employer(emp: dict, state: dict, now: datetime) -> str | None:
    """``"easy_apply"`` for an employer whose job page was read and shows no offsite apply link:
    there is nothing to follow, and the engine remembers it."""
    if emp.get("detailed") and not any(not sdk.is_job_board(link) for link in emp["links"]):
        return "easy_apply"
    return None
