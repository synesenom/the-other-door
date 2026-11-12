#!/usr/bin/env python3
"""Scraper for the Jobmaskinen hub (job.jobmaskinen.dk, DB Job ApS).

A keyword board: a WordPress plugin lists about 7,000 Danish ads, among them Jobnet's (jobnet.dk
needs a MitID login; the hub shows the same ads without one). Strong for trades, health and
public-sector jobs. The ads are Danish. `job.dsr.dk`, `job.finansforbundet.dk` and
`www.jobunivers.dk` run the same plugin over subsets of the hub's ads, so they are not read
separately (their hosts are in `dk.toml`'s `job_boards`, so `follow` never takes them for an employer).

Endpoint: ``GET /jobliste/?searchit=&searchjobtitel=<keyword>&searchbeliggenhed=&offset=<10n>``,
a search of the ad titles, 10 cards a page, newest first within the day. Page 1 sends no ``offset``
(``offset=0`` is answered with a redirect that drops the query); a page that has a next one links it
(``nav_jobright``). A card gives the ``?jobnet=<id>`` link, title (cut at about 90 characters), employer,
the job type, the place and the posting date; it has no text. A new ad costs one request to its page
``/jobliste/?jobnet=<id>``, which carries a ``JobPosting`` JSON-LD block (full title and text,
``datePosted``, address, ``hiringOrganization``, ``sourceOrganization: Jobnet``). An ad in `known_ids`
costs nothing, and with a freshness cutoff an ad dated before it neither. A page whose ad fails
keeps its card (the job type as the teaser). The place is not sent (``searchbeliggenhed`` is empty):
the hub lists Denmark. Requests pause `http_client.FEED_DELAY`; at most `_MAX_PAGES` pages a keyword;
a 403 or 429 stops the site for the run (`record_pushback`).

The job id is the Jobnet id, ``jobmaskinen.<id>``.

Terms: none found on the site (no terms page, no clause on automated access); checked 2026-10-31.
robots.txt: ``User-agent: *`` with an empty ``Disallow``, everything allowed.
"""

import json
import re
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from door.scrapers.sdk import (
    FEED_DELAY, JobPosting, PROBE_TIMEOUT_S, PoliteSession, ProbeResult, log_keyword_results, make_job_id,
    parse_iso_date, record_answered, record_error, record_pushback, report, run_probe, strip_html,
)

_SITE = "jobmaskinen"
_BASE = "https://job.jobmaskinen.dk"
_PAGE_SIZE = 10
_MAX_PAGES = 5
_MIN_DELAY, _MAX_DELAY = FEED_DELAY

# Hosts of this board: a link here is an ad on the board, never an employer's own site (`ats_detect.is_job_board`).
JOB_BOARD_HOSTS = ("jobmaskinen.",)

_JOBNET_ID = re.compile(r"[?&]jobnet=(\d+)")


class _Pushback(Exception):
    """The site refused (403 or 429): stop for this run."""


def _search_url(keyword: str, page: int) -> str:
    """The search of titles for *keyword*, 1-based *page*; page 1 has no ``offset``."""
    query = [("searchit", ""), ("searchjobtitel", keyword), ("searchbeliggenhed", "")]
    if page > 1:
        query.append(("offset", str((page - 1) * _PAGE_SIZE)))
    return f"{_BASE}/jobliste/?{urlencode(query)}"


def _job_url(job_id: str) -> str:
    return f"{_BASE}/jobliste/?jobnet={job_id}"


def _parse_card_date(text: str) -> datetime | None:
    """A card's ``dd-mm-yyyy`` posting date as midnight UTC; None when it is not one. Pure."""
    try:
        return datetime.strptime((text or "").strip(), "%d-%m-%Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _text(node) -> str:
    return node.get_text(" ", strip=True).replace("\xa0", " ").strip() if node else ""


def _parse_cards(html: str) -> tuple[list[dict], bool]:
    """The result cards of a search page and whether a next page is linked. Pure.

    A card is ``{platform_id, title, company, tag, place, posted_at}``; a page without cards is ``([], False)``.
    """
    soup = BeautifulSoup(html, "html.parser")
    cards: list[dict] = []
    for box in soup.select("div.dbj_jobbox"):
        link = box.select_one("h2.dbj_jobHeadline a[href]")
        match = _JOBNET_ID.search(link["href"]) if link else None
        if not match:
            continue
        date_div = box.find_previous_sibling("div", class_="aka_opslaaetdato")
        body = box.select_one("div.dbj_jobBody")
        place_div = body.find_next_sibling("div") if body else None
        cards.append({
            "platform_id": match.group(1),
            "title": _text(link),
            "company": _text(box.select_one("div.dbj_jobCompanyname")),
            "tag": _text(body),
            "place": _text(place_div).split("|")[0].strip(),
            "posted_at": _parse_card_date(_text(date_div)),
        })
    return cards, bool(cards) and soup.select_one("a.nav_jobright") is not None


def _is_results_page(html: str) -> bool:
    """Whether a page is the search's answer: result cards, or the results container holding the
    "no match" line. The container alone (its cards renamed) is not one. Pure."""
    soup = BeautifulSoup(html or "", "html.parser")
    if soup.select_one("div.dbj_jobbox h2.dbj_jobHeadline a[href]"):
        return True
    box = soup.select_one("div.dbj_jobJobliste")
    return box is not None and "Din søgning gav ingen match" in box.get_text(" ", strip=True)


def _parse_detail(html: str) -> dict | None:
    """``{title, company, location, description, posted_at}`` from an ad page's ``JobPosting`` JSON-LD
    (``posted_at`` the ISO string); None when the page has none. Pure."""
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if not isinstance(data, dict) or data.get("@type") != "JobPosting":
            continue
        address = (data.get("jobLocation") or {}).get("address") or {}
        return {
            "title": (data.get("title") or "").strip(),
            "company": ((data.get("hiringOrganization") or {}).get("name") or "").strip(),
            "location": (address.get("addressLocality") or "").strip(),
            "description": strip_html(data.get("description")),
            "posted_at": data.get("datePosted") or "",
        }
    return None


def _posting(card: dict, detail: dict | None, scraped_at: datetime) -> dict:
    """One JobPosting dict from a card and, when it was read, the ad page's detail."""
    detail = detail or {}
    platform_id = card["platform_id"]
    posted = parse_iso_date(detail.get("posted_at")) or card.get("posted_at")
    posting = JobPosting(
        id=make_job_id(_SITE, platform_id),
        title=detail.get("title") or card["title"],
        company=detail.get("company") or card["company"],
        location=detail.get("location") or card["place"],
        url=_job_url(platform_id),
        description=detail.get("description") or card["tag"],
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=platform_id,
        posted_at=posted,
    )
    return posting.model_dump(mode="json")


def _keywords(config: dict) -> list[str]:
    return list(config.get("search_keywords") or config.get("role_targets") or [])


def _get(session: PoliteSession, url: str) -> str:
    """The page's text; a 403 or 429 raises `_Pushback`, any other failure its own exception."""
    try:
        return session.get(url).text
    except requests.HTTPError as exc:
        if getattr(exc.response, "status_code", None) in (403, 429):
            raise _Pushback(f"HTTP {exc.response.status_code} on {url}") from exc
        raise


def _fail(message: str) -> None:
    report(message, site=_SITE)
    record_error(_SITE, message)


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """JobPosting dicts for the title searches of the profile's keywords.

    An ad in *known_ids* comes back as ``{"platform_id", "seen_only": True}`` with no request; an ad
    dated before ``kwargs["since"]`` is left out. Errors are recorded, never raised.
    """
    since = kwargs.get("since")
    if since is not None and since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    scraped_at = datetime.now(timezone.utc)
    session = PoliteSession(min_delay=_MIN_DELAY, max_delay=_MAX_DELAY)
    seen: set[str] = set()
    postings: list[dict] = []

    try:
        for keyword in _keywords(config):
            start = len(postings)
            for page in range(1, _MAX_PAGES + 1):
                url = _search_url(keyword, page)
                try:
                    html = _get(session, url)
                    cards, has_next = _parse_cards(html)
                except _Pushback:
                    raise
                except Exception as exc:
                    _fail(f"search error (keyword={keyword!r}, page={page}): {exc}")
                    break
                if not cards:
                    if _is_results_page(html):
                        record_answered(_SITE)
                    else:
                        _fail(f"search (keyword={keyword!r}, page={page}): no result cards or no-results marker "
                              "on the page (the site may have changed)")
                    break
                for card in cards:
                    platform_id = card["platform_id"]
                    if platform_id in seen:
                        continue
                    seen.add(platform_id)
                    if platform_id in known_ids:
                        postings.append({"platform_id": platform_id, "seen_only": True})
                        continue
                    if since and card["posted_at"] and card["posted_at"] < since:
                        continue
                    detail = None
                    try:
                        detail = _parse_detail(_get(session, _job_url(platform_id)))
                        if detail is None:
                            _fail(f"detail error ({_job_url(platform_id)}): no JobPosting data")
                    except _Pushback:
                        raise
                    except Exception as exc:
                        _fail(f"detail error ({_job_url(platform_id)}): {exc}")
                    postings.append(_posting(card, detail, scraped_at))
                if not has_next:
                    break
            log_keyword_results(_SITE, keyword, postings[start:])
    except _Pushback as exc:
        _fail(f"stopped for this run: {exc}")
        record_pushback(_SITE)
    return postings


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: page 1 of the first keyword's search, no ad pages.

    ``raw`` is the page's HTML. Never records errors; ``None`` when no keyword is configured.
    """
    keywords = _keywords(config)
    if not keywords:
        return None
    url = _search_url(keywords[0], 1)
    session = PoliteSession(min_delay=_MIN_DELAY, max_delay=_MAX_DELAY, timeout=PROBE_TIMEOUT_S, max_retries=0)

    def parse(html: str):
        cards, _ = _parse_cards(html)
        if not cards:
            if _is_results_page(html):
                return [], True, ""
            return [], False, "no result cards (div.dbj_jobbox) or no-results marker on the search page"
        scraped_at = datetime.now(timezone.utc)
        return [_posting(card, None, scraped_at) for card in cards], True, ""

    return run_probe(lambda: session.get(url).text, parse, "html")
