#!/usr/bin/env python3
"""Scraper for Reed (reed.co.uk), a large UK general job board.

Kind: a keyword board, plain HTTP, no login. Endpoints:
- search ``GET https://www.reed.co.uk/jobs/<keyword>-jobs-in-<place>[?pageno=<n>]`` (``<keyword>-jobs`` for
  a nationwide search). The page embeds its results in ``<script id="__NEXT_DATA__">``:
  ``props.pageProps.searchResults`` has ``count`` and ``jobs`` (25 a page), each with a ``jobDetail``
  (``jobId``, ``jobTitle``, ``ouName`` the employer, ``displayLocationName``, ``dateCreated``,
  ``jobDescriptionSnippet`` cut at about 200 characters, ``externalUrl``) and the ad's ``url``;
- ad ``GET https://www.reed.co.uk/jobs/<slug>/<id>`` - its schema.org ``JobPosting`` JSON-LD holds the
  full description (HTML).

The search is ranked by relevance and ``sortBy`` is never sent (robots.txt disallows it). A card whose
title is not on topic for the profile's keywords (``on_topic``) costs no ad request, nor does an id in
``known_ids`` (a ``seen_only`` record, as Jobindex's), nor an ad created before ``since`` (cut on
``dateCreated``; Reed's server-side date filter is not used). A keyword reads pages until the result
count is covered or a page is empty, at most ``max_pages_per_keyword`` (default 3). An ad whose page
cannot be read keeps its search snippet as the description, and the failure is recorded.

A 403 or 429 (after the session's backoff) or a challenge page is pushback: it is recorded with
``record_pushback`` and the run stops; a challenge is never worked around.

Terms: https://www.reed.co.uk/policies#termsConditions - "You may copy material on the Website for your own
private or domestic purposes, but no copying for any commercial or business use is permitted"; no clause on
bots, scraping or text-and-data mining (checked 2026-11-03). The official Reed API needs a key and is not used.
robots.txt (checked 2026-11-03) disallows ``/api/``, ``/handlers/``, ``/jobs/*?*sortBy=``,
``/*multipleParentSectorIds=`` and ``/*?directjob``; the search path and ``?pageno=`` are allowed.
"""

import json
import re
import unicodedata
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from door.scrapers.sdk import (
    FEED_DELAY, JobPosting, PROBE_TIMEOUT_S, PoliteSession, ProbeResult, log_keyword_results, make_job_id,
    on_topic, record_error, record_pushback, report, run_probe, strip_html, topic_terms,
)

_SITE = "reed"
_BASE = "https://www.reed.co.uk"
_MAX_PAGES = 3
_PAGE_SIZE = 25

# Pause between requests: the employer feeds' (one host, one at a time).
_MIN_DELAY, _MAX_DELAY = FEED_DELAY

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

# Hosts of this board: a link here is an ad on the board, never an employer's own site (`ats_detect.is_job_board`).
JOB_BOARD_HOSTS = ("reed.co.uk",)

_CHALLENGE_MARKERS = ("just a moment", "cdn-cgi/challenge-platform", "attention required", "cf-chl", "cf-browser-verification")
_NEXT_DATA = re.compile(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_LD_JSON = re.compile(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.S | re.I)
# Locations that name no place Reed could search in: the whole country is searched.
_NATIONWIDE = {"", "uk", "united kingdom", "great britain", "gb", "england", "britain", "remote", "anywhere"}


class _Pushback(Exception):
    """The site refused the request (a 403/429 or a challenge page); the run stops."""


def _slug(text: str) -> str:
    folded = unicodedata.normalize("NFD", text.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")


def _search_url(keyword: str, location: str, page: int = 1) -> str:
    """The search URL of *keyword* in the place named first in *location* (the whole UK when it names none). Pure."""
    place = (location or "").split(",")[0].strip()
    slug = _slug(place) if place.lower() not in _NATIONWIDE else ""
    path = f"{_slug(keyword)}-jobs" + (f"-in-{slug}" if slug else "")
    return f"{_BASE}/jobs/{path}" + (f"?pageno={page}" if page > 1 else "")


def _parse_results(html: str) -> tuple[int, list[dict]] | None:
    """``(count, jobs)`` of a search page; None when its results block is missing. Pure."""
    m = _NEXT_DATA.search(html or "")
    if not m:
        return None
    try:
        results = json.loads(m.group(1))["props"]["pageProps"]["searchResults"]
        jobs = results["jobs"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(jobs, list):
        return None
    try:
        count = int(results.get("count") or len(jobs))
    except (TypeError, ValueError):
        count = len(jobs)
    return count, [j for j in jobs if isinstance(j, dict)]


def _parse_date(value) -> datetime | None:
    """A Reed timestamp (naive local time, optionally with a ``Z``) as a naive datetime. Pure."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _card(raw: dict) -> dict | None:
    """The fields of one search result; None without an id or a title. Pure."""
    detail = raw.get("jobDetail") if isinstance(raw, dict) else None
    if not isinstance(detail, dict) or not detail.get("jobId") or not str(detail.get("jobTitle") or "").strip():
        return None
    pid = str(detail["jobId"])
    path = raw.get("url") or f"/jobs/job/{pid}"
    return {
        "id": pid,
        "url": path if path.startswith("http") else _BASE + path,
        "title": re.sub(r"\s+", " ", str(detail["jobTitle"])).strip(),
        "company": re.sub(r"\s+", " ", str(detail.get("ouName") or "")).strip(),
        "location": str(detail.get("displayLocationName") or detail.get("countyLocation") or "").strip(),
        "created": _parse_date(detail.get("dateCreated")),
        "external_url": str(detail.get("externalUrl") or ""),
        "snippet": strip_html(str(detail.get("jobDescriptionSnippet") or "")),
    }


def _parse_description(html: str) -> str | None:
    """The plain-text description of the ad's ``JobPosting`` JSON-LD; None when the page has none. Pure."""
    for block in _LD_JSON.findall(html or ""):
        try:
            data = json.loads(block, strict=False)
        except ValueError:
            continue
        for node in data if isinstance(data, list) else [data]:
            if isinstance(node, dict) and node.get("@type") == "JobPosting" and node.get("description"):
                text = BeautifulSoup(str(node["description"]), "html.parser").get_text("\n", strip=True)
                return text or None
    return None


def _is_challenge(body: str, status: int) -> bool:
    """Whether an answer is a refusal or a challenge page, not the site. Pure."""
    if status in (403, 429):
        return True
    head = (body or "")[:6000].lower()
    return any(marker in head for marker in _CHALLENGE_MARKERS) and "__next_data__" not in head


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


def _posting(card: dict, description: str, scraped_at: datetime) -> dict:
    external = card["external_url"]
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
        posted_at=card["created"],
        apply_type="external" if external else None,
        apply_url=external or None,
    ).model_dump(mode="json")


def _pushback(message: str) -> None:
    report(f"{_SITE}: {message}; stopping for this run")
    record_error(_SITE, f"{_SITE}: {message}; stopped for this run")
    record_pushback(_SITE)


def _naive(moment: datetime | None) -> datetime | None:
    return moment.replace(tzinfo=None) if moment is not None else None


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """JobPosting dicts for the on-topic ads of every search keyword (``seen_only`` records for known ids)."""
    keywords: list[str] = config.get("search_keywords") or config.get("role_targets") or []
    location = config.get("location", "")
    max_pages = int(config.get("max_pages_per_keyword", _MAX_PAGES))
    since = _naive(kwargs.get("since"))
    topic = topic_terms(config)
    scraped_at = datetime.now(timezone.utc)
    session = PoliteSession(min_delay=_MIN_DELAY, max_delay=_MAX_DELAY, timeout=20, headers=_HEADERS)
    seen: set[str] = set()
    out: list[dict] = []

    for keyword in keywords:
        start = len(out)
        for page in range(1, max_pages + 1):
            try:
                parsed = _parse_results(_get(session, _search_url(keyword, location, page)))
            except _Pushback as exc:
                _pushback(str(exc))
                return out
            except Exception as exc:  # noqa: BLE001 - one bad page never stops the run
                report(f"search error (keyword={keyword!r}, page={page}): {exc}")
                record_error(_SITE, f"search error (keyword={keyword!r}, page={page}): {exc}")
                break
            if parsed is None:
                report(f"no search results block on page (keyword={keyword!r}, page={page})")
                record_error(_SITE, f"no search results block on page (keyword={keyword!r}, page={page})")
                break
            count, jobs = parsed
            cards = [c for c in (_card(j) for j in jobs) if c]

            for card in cards:
                if card["id"] in seen or (topic and not on_topic(card["title"], topic)):
                    continue
                if since is not None and card["created"] is not None and card["created"] < since:
                    continue
                seen.add(card["id"])
                if card["id"] in known_ids:
                    out.append({"platform_id": card["id"], "seen_only": True})
                    continue
                report(f"'{keyword}' details", len(out) - start + 1, len(cards))
                description = None
                try:
                    description = _parse_description(_get(session, card["url"]))
                    if description is None:
                        raise ValueError("no JobPosting data on the page")
                except _Pushback as exc:
                    _pushback(str(exc))
                    return out
                except Exception as exc:  # noqa: BLE001 - the snippet is the fallback
                    report(f"detail error ({card['url']}): {exc}")
                    record_error(_SITE, f"detail error ({card['url']}): {exc}")
                out.append(_posting(card, description or card["snippet"], scraped_at))

            if not jobs or page * _PAGE_SIZE >= count:
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
        parsed = _parse_results(html)
        if parsed is None:
            return [], False, "no search results block (__NEXT_DATA__ searchResults) on the page"
        scraped_at = datetime.now(timezone.utc)
        cards = [c for c in (_card(j) for j in parsed[1]) if c]
        return [_posting(c, c["snippet"], scraped_at) for c in cards], True, ""

    result = run_probe(fetch, parse, "html")
    if str(result.get("reason", "")).startswith("bot-wall"):
        result["wall"] = True
    return result
