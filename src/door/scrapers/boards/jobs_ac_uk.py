#!/usr/bin/env python3
"""Scraper for jobs.ac.uk, the UK's academic job board (research, lecturing, professional services).

Kind: a keyword board, plain HTTP, no login, server-rendered HTML. Endpoints:
- search ``GET https://www.jobs.ac.uk/search/?keywords=<kw>&sortOrder=1&pageSize=25&startIndex=<1+25n>``:
  ``sortOrder=1`` is "Date Placed" (newest first; 0 is relevance, 2 the closing date). Each result is a
  ``div.j-search-result__result[data-advert-id]`` with the title link (``/job/<code>/<slug>``), the
  department, the employer, ``Location:``, ``Salary:``, ``Date Placed: 03 Nov`` (day and month only)
  and the closing date. ``strong.job-count`` holds the number of hits, a ``Next`` link the next page.
  The ``location=`` parameter does not narrow the list (``placeId`` is set by the page's JavaScript
  autocomplete), but the page's own ``locationFacet[]=<slug>`` does: it is sent for a profile city
  The other door knows (``locationFacet[]=london``), otherwise the cards are filtered on their location
  text (``sdk.location_fits``: the city, its commute area, remote and unknown places stay);
- ad ``GET https://www.jobs.ac.uk/job/<code>/<slug>`` - its schema.org ``JobPosting`` JSON-LD holds the
  full description (HTML) and the exact ``datePosted``.

The placed date has no year: the latest date that is not in the future is taken (a date after today
means last year). The list is newest first, so a keyword stops at the first card placed before ``since``.
A card whose title is not on topic (``on_topic``), whose location does not suit the profile, or whose id
is in ``known_ids`` (a ``seen_only`` record) costs no ad request. A keyword reads pages until there is no
``Next`` link, at most ``max_pages_per_keyword`` (default 3). An ad whose page cannot be read keeps a
description built from its card, and the failure is recorded. No language filter: the board is in English.

A 403 or 429 (after the session's backoff) or a challenge page is pushback: it is recorded with
``record_pushback`` and the run stops.

Terms: https://www.jobs.ac.uk/legal/terms-and-conditions - "You can download, print and copy material
from the Company's Website for your own personal use. You must not reproduce any part of the Company's
Website or its material unless the Company have granted you permission to do so."; no clause on bots,
scraping, automated access or text-and-data mining (checked 2026-11-03). Operator: Warwick University
Services Limited. robots.txt (checked 2026-11-03) disallows only ``/job/feedback/`` and ``/enhanced/fp/``.
"""

import json
import re
import unicodedata
from urllib.parse import quote_plus
from datetime import date, datetime, timezone

import requests
from bs4 import BeautifulSoup

from door.scrapers import sdk
from door.scrapers.sdk import (
    FEED_DELAY, JobPosting, PROBE_TIMEOUT_S, PoliteSession, ProbeResult, log_keyword_results, make_job_id,
    on_topic, parse_iso_date, record_answered, record_error, record_pushback, report, run_probe, topic_terms,
)

_SITE = "jobs_ac_uk"
_BASE = "https://www.jobs.ac.uk"
_MAX_PAGES = 3
_PAGE_SIZE = 25
_NEWEST_FIRST = 1  # sortOrder: 0 relevance, 1 date placed, 2 closing date

_MIN_DELAY, _MAX_DELAY = FEED_DELAY

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

# Hosts of this board: a link here is an ad on the board, never an employer's own site (`ats_detect.is_job_board`).
JOB_BOARD_HOSTS = ("jobs.ac.uk",)

_CHALLENGE_MARKERS = ("just a moment", "cdn-cgi/challenge-platform", "attention required", "cf-chl", "cf-browser-verification")
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_PLACED = re.compile(r"(\d{1,2})\s+([A-Za-z]{3})")


class _Pushback(Exception):
    """The site refused the request (a 403/429 or a challenge page); the run stops."""


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _slug(text: str) -> str:
    folded = unicodedata.normalize("NFD", text.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")


def _search_url(keyword: str, location: str, page: int = 1) -> str:
    """The newest-first search URL of *keyword*; the place named first in *location* becomes the page's
    location facet when it is a city The other door knows. Pure."""
    query = quote_plus(keyword.strip())
    url = f"{_BASE}/search/?keywords={query}&sortOrder={_NEWEST_FIRST}&pageSize={_PAGE_SIZE}&startIndex={(page - 1) * _PAGE_SIZE + 1}"
    place = (location or "").split(",")[0].strip()
    if place and sdk.known_city(place):
        url += f"&locationFacet%5B%5D={_slug(place)}"
    return url


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ")).strip() if node is not None else ""


def _labelled(block, label: str) -> str:
    """The text after a ``Label:`` in a card's ``div`` (``Location: London``); empty when absent."""
    for div in block.find_all("div"):
        text = _text(div)
        if text.startswith(label) and not div.find("div"):
            return text[len(label):].strip()
    return ""


def _parse_cards(html: str) -> list[dict] | None:
    """The cards of a search page; None when neither results nor a hit count are on it. Pure."""
    soup = BeautifulSoup(html or "", "html.parser")
    blocks = soup.select("div.j-search-result__result")
    if not blocks and soup.select_one(".job-count") is None:
        return None
    cards = []
    for block in blocks:
        link = block.select_one("a[href^='/job/']")
        pid = block.get("data-advert-id")
        title = _text(link)
        if link is None or not pid or not title:
            continue
        placed = _PLACED.search(_labelled(block, "Date Placed:"))
        month = _MONTHS.get(placed.group(2).lower()) if placed else None
        cards.append({
            "id": str(pid),
            "title": title,
            "url": _BASE + link["href"].split("?")[0],
            "company": _text(block.select_one(".j-search-result__employer")),
            "department": _text(block.select_one(".j-search-result__department")),
            "location": _labelled(block, "Location:"),
            "salary": _labelled(block, "Salary:"),
            "placed": (int(placed.group(1)), month) if placed and month else None,
        })
    return cards


def _parse_count(html: str) -> int | None:
    """The number of hits of a search page. Pure."""
    m = re.search(r'class="job-count"[^>]*>\s*([\d,]+)', html or "")
    return int(m.group(1).replace(",", "")) if m else None


def _has_next(html: str) -> bool:
    """Whether the page links to a next page. Pure."""
    return any(_text(a) == "Next" for a in BeautifulSoup(html or "", "html.parser").select("a[href*='startIndex=']"))


def _placed_date(day: int, month: int, today: date) -> datetime | None:
    """The latest date with this day and month that is not after *today* (the board writes no year). Pure."""
    for year in range(today.year, today.year - 9, -1):
        try:
            moment = date(year, month, day)
        except ValueError:
            continue
        if moment <= today:
            return datetime(year, month, day)
    return None


def _html_text(html: str) -> str:
    """Plain text of an HTML fragment: one line per block element, inline markup kept in its line. Pure."""
    broken = re.sub(r"(</(?:p|li|h\d|div|ul|ol|tr)>|<br\s*/?>)", r"\1\n", html)
    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in BeautifulSoup(broken, "html.parser").get_text("").splitlines())
    return "\n".join(line for line in lines if line)


def _parse_detail(html: str) -> dict | None:
    """``{"description", "posted"}`` of the ad's ``JobPosting`` JSON-LD (plain-text description, exact date or
    None); None when the page has none. Pure."""
    for block in re.findall(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", html or "", re.S | re.I):
        try:
            data = json.loads(block, strict=False)
        except ValueError:
            continue
        for node in data if isinstance(data, list) else [data]:
            if isinstance(node, dict) and node.get("@type") == "JobPosting" and node.get("description"):
                text = _html_text(str(node["description"]))
                if text:
                    posted = parse_iso_date(node.get("datePosted"))
                    return {"description": text, "posted": posted.replace(tzinfo=None) if posted else None}
    return None


def _card_text(card: dict) -> str:
    """A description from a card alone (the fallback when the ad page cannot be read)."""
    parts = [card["title"], card["department"], card["company"]]
    if card["location"]:
        parts.append(f"Location: {card['location']}")
    if card["salary"]:
        parts.append(f"Salary: {card['salary']}")
    return ". ".join(p for p in parts if p)


def _is_challenge(body: str, status: int) -> bool:
    """Whether an answer is a refusal or a challenge page, not the site. Pure."""
    if status in (403, 429):
        return True
    head = (body or "")[:6000].lower()
    return any(marker in head for marker in _CHALLENGE_MARKERS)


def _get(session: PoliteSession, url: str) -> str:
    """The page at *url*. Raises `_Pushback` on a refusal or a challenge, the request's own error otherwise."""
    try:
        resp = session.get(url)
    except requests.HTTPError as exc:
        status = getattr(exc.response, "status_code", 0)
        if _is_challenge("", status):
            raise _Pushback(f"HTTP {status}") from exc
        raise
    if _is_challenge(resp.text, resp.status_code):
        raise _Pushback("challenge page")
    return resp.text


def _posting(card: dict, description: str, posted: datetime | None, scraped_at: datetime) -> dict:
    return JobPosting(
        id=make_job_id(_SITE, card["id"]),
        title=card["title"],
        company=card["company"],
        location=card["location"],
        url=card["url"],
        description=description,
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=card["id"],
        posted_at=posted,
    ).model_dump(mode="json")


def _card_date(card: dict) -> datetime | None:
    return _placed_date(*card["placed"], _today()) if card["placed"] else None


def _pushback(message: str) -> None:
    report(f"{_SITE}: {message}; stopping for this run")
    record_error(_SITE, f"{_SITE}: {message}; stopped for this run")
    record_pushback(_SITE)


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """JobPosting dicts for the on-topic ads of every search keyword (``seen_only`` records for known ids)."""
    keywords: list[str] = config.get("search_keywords") or config.get("role_targets") or []
    location = config.get("location", "")
    max_pages = int(config.get("max_pages_per_keyword", _MAX_PAGES))
    since = kwargs.get("since")
    since_day = since.date() if since is not None else None
    topic = topic_terms(config)
    scraped_at = datetime.now(timezone.utc)
    session = PoliteSession(min_delay=_MIN_DELAY, max_delay=_MAX_DELAY, timeout=20, headers=_HEADERS)
    seen: set[str] = set()
    out: list[dict] = []

    for keyword in keywords:
        start = len(out)
        done = False
        for page in range(1, max_pages + 1):
            try:
                html = _get(session, _search_url(keyword, location, page))
            except _Pushback as exc:
                _pushback(str(exc))
                return out
            except Exception as exc:  # noqa: BLE001 - one bad page never stops the run
                report(f"search error (keyword={keyword!r}, page={page}): {exc}")
                record_error(_SITE, f"search error (keyword={keyword!r}, page={page}): {exc}")
                break
            cards = _parse_cards(html)
            if cards is None:
                report(f"no search results block on page (keyword={keyword!r}, page={page})")
                record_error(_SITE, f"no search results block on page (keyword={keyword!r}, page={page})")
                break
            if not cards:
                record_answered(_SITE)

            for card in cards:
                placed = _card_date(card)
                if since_day is not None and placed is not None and placed.date() < since_day:
                    done = True  # newest first: every later card is older too
                    break
                if card["id"] in seen or (topic and not on_topic(card["title"], topic)):
                    continue
                if not sdk.location_fits(card["location"], config) or not sdk.keep_local(
                        [{"location": card["location"]}], config, _SITE):
                    continue
                seen.add(card["id"])
                if card["id"] in known_ids:
                    out.append({"platform_id": card["id"], "seen_only": True})
                    continue
                report(f"'{keyword}' details", len(out) - start + 1, len(cards))
                detail = None
                try:
                    detail = _parse_detail(_get(session, card["url"]))
                    if detail is None:
                        raise ValueError("no JobPosting data on the page")
                except _Pushback as exc:
                    _pushback(str(exc))
                    return out
                except Exception as exc:  # noqa: BLE001 - the card is the fallback
                    report(f"detail error ({card['url']}): {exc}")
                    record_error(_SITE, f"detail error ({card['url']}): {exc}")
                description = detail["description"] if detail else _card_text(card)
                posted = (detail or {}).get("posted") or placed
                out.append(_posting(card, description, posted, scraped_at))

            if done or not cards or not _has_next(html):
                break
        log_keyword_results(_SITE, keyword, [p for p in out[start:] if not p.get("seen_only")])
    return out


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: page 1 of the first keyword, no ad requests.

    ``raw`` is the page's HTML. Never records errors; ``None`` when no keyword is configured.
    """
    keywords = config.get("search_keywords") or config.get("role_targets") or []
    if not keywords:
        return None
    session = PoliteSession(min_delay=_MIN_DELAY, max_delay=_MAX_DELAY, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)
    url = _search_url(keywords[0], config.get("location", ""), 1)

    def fetch() -> str:
        return session.get(url).text

    def parse(html: str):
        if _is_challenge(html, 200):
            return [], False, "bot-wall: a challenge page"
        cards = _parse_cards(html)
        if cards is None:
            return [], False, "no search results block (div.j-search-result__result, .job-count) on the page"
        scraped_at = datetime.now(timezone.utc)
        return [_posting(c, _card_text(c), _card_date(c), scraped_at) for c in cards], True, ""

    result = run_probe(fetch, parse, "html")
    if str(result.get("reason", "")).startswith("bot-wall"):
        result["wall"] = True
    return result
