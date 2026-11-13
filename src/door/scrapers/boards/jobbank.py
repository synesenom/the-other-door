#!/usr/bin/env python3
"""Scraper for Akademikernes Jobbank (jobbank.dk).

Kind: a keyword board (DM, Djøf and IDA post here), plain HTTP, server-rendered HTML, no login.
Endpoints:
- search ``GET https://jobbank.dk/job/?key=<keyword>&page=<n>`` - 20 cards per page
  (``div.job-item``: link ``/job/<id>/<company>/<title>/``, ``.job-header`` the title,
  ``.job-teaser`` "Fuldtidsjob hos <company>, <region>", ``.job-date-updated``);
- ad ``GET https://jobbank.dk/job/<id>/`` - its schema.org ``JobPosting`` JSON-LD holds the
  description (HTML), ``datePosted``, ``validThrough``, ``hiringOrganization`` and ``jobLocation``.

The search is full text and ranked by relevance, so it is noisy: a card whose title is not on
topic for the profile's keywords (``on_topic``) costs no ad request and is dropped. An ad whose id
is in ``known_ids`` costs none either (a ``seen_only`` record, as Jobindex's). A keyword reads
pages until a short or empty page, at most ``max_pages_per_keyword`` (default 3). The site has no
age filter; the freshness cutoff is left to ``find``.

Cloudflare sits in front of the site. A 403 or 429 (after the session's backoff) or a challenge
page is pushback: it is recorded with ``record_pushback`` (the site rests for
``Site.cooldown_hours``) and the run stops; a challenge is never worked around.

Terms: https://jobbank.dk/brugerbetingelser - no clause on automated access or on text-and-data mining.
robots.txt (checked 2026-10-31) allows ``/job/`` for every agent and disallows ``/profil/``, ``/ajax/``,
``/redirect/`` and a few others; it names no ``Crawl-delay`` for browsers.
"""

import html as html_lib
import json
import re
from datetime import datetime, timezone
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from door.scrapers.sdk import (
    FEED_DELAY, JobPosting, PROBE_TIMEOUT_S, PoliteSession, ProbeResult, log_keyword_results, make_job_id,
    on_topic, record_answered, record_error, record_pushback, report, run_probe, strip_html, topic_terms,
)

_SITE = "jobbank"
_BASE = "https://jobbank.dk"
_MAX_PAGES = 3
_PAGE_SIZE = 20

# Pause between requests: the employer feeds' (one host, one at a time).
_MIN_DELAY, _MAX_DELAY = FEED_DELAY

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "da,en;q=0.9",
}

# Hosts of this board: a link here is an ad on the board, never an employer's own site (`ats_detect.is_job_board`).
JOB_BOARD_HOSTS = ("jobbank.",)

_CHALLENGE_MARKERS = ("just a moment", "cdn-cgi/challenge-platform", "attention required", "cf-chl", "cf-browser-verification")
_ID_IN_PATH = re.compile(r"^/job/(\d+)/")
_UPDATED = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
_LD_JSON = re.compile(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.S | re.I)


class _Pushback(Exception):
    """The site refused the request (a 403/429 or a challenge page); the run stops."""


def _search_url(keyword: str, page: int) -> str:
    return f"{_BASE}/job/?key={quote_plus(keyword)}&page={page}"


def _detail_url(platform_id: str) -> str:
    return f"{_BASE}/job/{platform_id}/"


def _is_challenge(body: str, status: int) -> bool:
    """Whether an answer is Cloudflare's refusal or challenge, not the site. Pure."""
    if status in (403, 429):
        return True
    head = (body or "")[:6000].lower()
    return any(marker in head for marker in _CHALLENGE_MARKERS) and "job-item" not in head


def _parse_teaser(text: str) -> tuple[str, str]:
    """``("<company>", "<region(s)>")`` of "Fuldtidsjob hos <company>, <region>"; ``("", "")`` when it has no "hos". Pure."""
    text = re.sub(r"\s+", " ", text or "").strip()
    _, found, rest = text.partition(" hos ")
    if not found:
        return "", ""
    company, _, region = rest.partition(",")
    return company.strip(), region.strip()


def _parse_card_date(text: str) -> datetime | None:
    """The date of "Opdateret: 06.10.2026" (naive); None for anything else. Pure."""
    m = _UPDATED.search(text or "")
    if not m:
        return None
    try:
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _says_no_hits(html: str) -> bool:
    """Whether the page is Akademikernes Jobbank's own results page (its title counts the relevant jobs, none included)."""
    return "relevante job" in html


def _parse_cards(html: str) -> list[dict]:
    """The result cards of a search page: ``id``, ``url``, ``title``, ``company``, ``region``, ``updated``. Pure."""
    soup = BeautifulSoup(html or "", "html.parser")
    cards = []
    for item in soup.select("div.job-item"):
        link = item.select_one("a[href^='/job/']")
        m = _ID_IN_PATH.match(link["href"]) if link else None
        header = item.select_one(".job-header")
        if not m or header is None:
            continue
        teaser = item.select_one(".job-teaser")
        # The remote-work note sits in a span of the teaser; the company and region are its own text.
        own = "".join(teaser.find_all(string=True, recursive=False)) if teaser is not None else ""
        company, region = _parse_teaser(own)
        updated = item.select_one(".job-date-updated")
        cards.append({
            "id": m.group(1),
            "url": _detail_url(m.group(1)),
            "title": re.sub(r"\s+", " ", header.get_text(" ", strip=True)),
            "company": company,
            "region": region,
            "updated": _parse_card_date(updated.get_text(" ", strip=True) if updated else ""),
        })
    return cards


def _location_text(address) -> str:
    """The place of a JSON-LD ``address`` (its locality); "" when there is none. Pure."""
    if isinstance(address, dict):
        return str(address.get("addressLocality") or "").strip()
    return str(address or "").strip()


def _parse_date(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _parse_detail(html: str) -> dict | None:
    """``title``, ``company``, ``location``, ``description`` (plain text), ``posted_at`` from the ad's
    ``JobPosting`` JSON-LD; None when the page has none. Pure."""
    for block in _LD_JSON.findall(html or ""):
        try:
            data = json.loads(block, strict=False)
        except ValueError:
            continue
        for node in data if isinstance(data, list) else [data]:
            if not isinstance(node, dict) or node.get("@type") != "JobPosting":
                continue
            org = node.get("hiringOrganization")
            place = node.get("jobLocation")
            if isinstance(place, list):
                place = place[0] if place else None
            return {
                "title": html_lib.unescape(str(node.get("title") or "")).strip(),
                "company": html_lib.unescape(str((org or {}).get("name") if isinstance(org, dict) else org or "")).strip(),
                "location": _location_text((place or {}).get("address") if isinstance(place, dict) else place),
                "description": strip_html(str(node.get("description") or "")),
                "posted_at": _parse_date(node.get("datePosted")),
            }
    return None


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


def _posting(card: dict, detail: dict, scraped_at: datetime) -> dict:
    return JobPosting(
        id=make_job_id(_SITE, card["id"]),
        title=detail["title"] or card["title"],
        company=detail["company"] or card["company"],
        location=detail["location"] or card["region"],
        url=card["url"],
        description=detail["description"],
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=card["id"],
        posted_at=detail["posted_at"] or card["updated"],
    ).model_dump(mode="json")


def _card_posting(card: dict, scraped_at: datetime) -> dict:
    """A posting from a search card alone (the probe's; no description)."""
    return _posting(card, {"title": "", "company": "", "location": "", "description": "", "posted_at": None}, scraped_at)


def _pushback(message: str) -> None:
    report(f"{_SITE}: {message}; stopping for this run")
    record_error(_SITE, f"{_SITE}: {message} (Cloudflare); stopped for this run")
    record_pushback(_SITE)


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """JobPosting dicts for the on-topic ads of every search keyword (``seen_only`` records for known ids)."""
    keywords: list[str] = config.get("search_keywords") or config.get("role_targets") or []
    max_pages = int(config.get("max_pages_per_keyword", _MAX_PAGES))
    topic = topic_terms(config)
    scraped_at = datetime.now(timezone.utc)
    session = PoliteSession(min_delay=_MIN_DELAY, max_delay=_MAX_DELAY, timeout=20, headers=_HEADERS)
    seen: set[str] = set()
    out: list[dict] = []

    for keyword in keywords:
        start = len(out)
        for page in range(1, max_pages + 1):
            url = _search_url(keyword, page)
            try:
                html = _get(session, url)
                cards = _parse_cards(html)
            except _Pushback as exc:
                _pushback(str(exc))
                return out
            except Exception as exc:  # noqa: BLE001 - one bad page never stops the run
                report(f"search error (keyword={keyword!r}, page={page}): {exc}")
                record_error(_SITE, f"search error (keyword={keyword!r}, page={page}): {exc}")
                break

            if not cards and _says_no_hits(html):
                record_answered(_SITE)
            for card in cards:
                if card["id"] in seen or (topic and not on_topic(card["title"], topic)):
                    continue
                seen.add(card["id"])
                if card["id"] in known_ids:
                    out.append({"platform_id": card["id"], "seen_only": True})
                    continue
                report(f"'{keyword}' details", len(out) - start + 1, len(cards))
                try:
                    detail = _parse_detail(_get(session, card["url"]))
                except _Pushback as exc:
                    _pushback(str(exc))
                    return out
                except Exception as exc:  # noqa: BLE001
                    report(f"detail error ({card['url']}): {exc}")
                    record_error(_SITE, f"detail error ({card['url']}): {exc}")
                    continue
                if detail is None:
                    report(f"detail error ({card['url']}): no JobPosting data")
                    record_error(_SITE, f"detail error ({card['url']}): no JobPosting data on the page")
                    continue
                out.append(_posting(card, detail, scraped_at))

            if len(cards) < _PAGE_SIZE:
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
    url = _search_url(keywords[0], 1)

    def fetch() -> str:
        resp = session.get(url)
        return resp.text

    def parse(html: str):
        if _is_challenge(html, 200):
            return [], False, "bot-wall: a Cloudflare challenge page"
        cards = _parse_cards(html)
        # The results block is the job list; a page with a title saying there are none is an empty answer.
        if not cards and not _says_no_hits(html):
            return [], False, "no job cards and no result count on the page"
        scraped_at = datetime.now(timezone.utc)
        return [_card_posting(c, scraped_at) for c in cards], True, ""

    result = run_probe(fetch, parse, "html")
    if str(result.get("reason", "")).startswith("bot-wall"):
        result["wall"] = True
    return result
