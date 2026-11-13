#!/usr/bin/env python3
"""Scraper for ReliefWeb (reliefweb.int), the UN OCHA job board for humanitarian and development work.

Endpoint: ``https://reliefweb.int/jobs/rss.xml?search=<keyword>``, the site's public RSS feed (no account;
the v2 API needs an approved app name, so it is not used). One request per search keyword returns the 20
newest matching jobs; the feed has no paging (``page`` and ``offset`` are ignored), so a keyword sees
only its newest 20. An item carries the title, link (``/job/<id>/<slug>``, the id is the platform id),
``pubDate``, ``author`` (the employer) and, in the escaped-HTML description, a ``Country:`` tag (or
``Countries:``), the closing date and the whole ad. No tag means no country (home-based or worldwide).

The location is the tagged countries; a job that says it is home-based (or remote, hybrid, in any supported
language: ``sdk.is_remote`` over the title and the start of the body) gets ``Home-based`` in front of
them. ReliefWeb serves the world, so the scraper applies ``sdk.keep_local`` itself: a profile gets only
local, home-based and country-less jobs (the drops are counted with ``record_non_local``).

Parsing (``_parse_feed``, ``_location_text``, ``_is_home_based``) is pure and tested from saved feeds.

Terms: https://reliefweb.int/terms-conditions - the Materials may be copied for personal, non-commercial
use, not resold or redistributed; nothing on automated access. robots.txt: no rule for the feed.
"""

import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
from xml.etree import ElementTree

from door.scrapers import sdk
from door.scrapers.sdk import (
    FEED_DELAY, JobPosting, PoliteSession, PROBE_TIMEOUT_S, ProbeResult, log_keyword_results, make_job_id, record_answered, record_error,
    report, run_probe, strip_html,
)

_FEED_URL = "https://reliefweb.int/jobs/rss.xml"
_MIN_DELAY, _MAX_DELAY = FEED_DELAY

# Hosts of this board: a link here is an ad on the board, never an employer's own site (`ats_detect.is_job_board`).
JOB_BOARD_HOSTS = ("reliefweb.",)

# The site's load balancer sometimes answers 202 with no body instead of the feed (#537): wait this long, ask once more.
_EMPTY_RETRY_PAUSE_S = 30

# How much of an ad's body is read for a home-based word (the rest is the employer's boilerplate).
_BODY_HEAD = 1500

_JOB_ID = re.compile(r"/job/(\d+)")
_TAG_DIV = re.compile(r'<div class="(?:tag|date)[^"]*">.*?</div>', re.S)
_COUNTRY_DIV = re.compile(r'<div class="tag country">\s*Countr(?:y|ies):\s*(.*?)\s*</div>', re.S)
_SOURCE_DIV = re.compile(r'<div class="tag source">\s*Organi[sz]ation:\s*(.*?)\s*</div>', re.S)


def _feed_url(keyword: str) -> str:
    return f"{_FEED_URL}?search={quote_plus(keyword)}"


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw.strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _parse_feed(xml_text: str) -> list[dict]:
    """The items of a ReliefWeb RSS feed as dicts (``platform_id``, ``title``, ``company``, ``countries``,
    ``url``, ``posted_at``, ``description``). ValueError when the text is not an RSS feed. Pure."""
    if not xml_text.strip():
        raise ValueError("empty answer, not the feed (the site's firewall may be holding the request)")
    try:
        root = ElementTree.fromstring(xml_text.encode("utf-8"))
    except ElementTree.ParseError as exc:
        raise ValueError(f"not an XML feed: {exc}") from exc
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise ValueError("not an RSS feed")
    items = []
    for item in channel.findall("item"):
        link = (item.findtext("link") or "").strip()
        match = _JOB_ID.search(link)
        if not match:
            continue
        html = item.findtext("description") or ""
        country = _COUNTRY_DIV.search(html)
        source = _SOURCE_DIV.search(html)
        company = (item.findtext("author") or "").strip() or (strip_html(source.group(1)) if source else "")
        items.append({
            "platform_id": match.group(1),
            "title": (item.findtext("title") or "").strip(),
            "company": company,
            "countries": [c.strip() for c in strip_html(country.group(1)).split(",") if c.strip()] if country else [],
            "url": link,
            "posted_at": _parse_date(item.findtext("pubDate")),
            "description": strip_html(_TAG_DIV.sub("", html)),
        })
    return items


def _fetch_feed(session: PoliteSession, url: str) -> str:
    """The feed text of *url*. An empty body (the load balancer's 202 challenge) is asked for once more after a
    pause, then raised as a clear error."""
    for attempt in range(2):
        resp = session.get(url)
        if resp.text.strip():
            return resp.text
        if attempt == 0:
            time.sleep(_EMPTY_RETRY_PAUSE_S)
    raise ValueError(f"empty answer (HTTP {resp.status_code}) twice, not the feed")


def _is_home_based(title: str, body: str) -> bool:
    """Whether the ad says it is home-based, remote or hybrid: in the title or the start of the body."""
    return sdk.is_remote(title) or sdk.is_remote(body[:_BODY_HEAD])


def _location_text(countries: list[str], home_based: bool) -> str:
    places = ", ".join(countries)
    if home_based:
        return f"Home-based, {places}" if places else "Home-based"
    return places


def _to_posting(item: dict, scraped_at: datetime) -> dict:
    platform_id = item["platform_id"]
    posting = JobPosting(
        id=make_job_id("reliefweb", platform_id),
        title=item["title"],
        company=item["company"],
        location=_location_text(item["countries"], _is_home_based(item["title"], item["description"])),
        url=item["url"],
        description=item["description"],
        source="reliefweb",
        scraped_at=scraped_at,
        platform_id=platform_id,
        posted_at=item["posted_at"],
    )
    return posting.model_dump(mode="json")


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Return JobPosting dicts from ReliefWeb: one feed per search keyword, newest first."""
    keywords = config.get("search_keywords") or config.get("role_targets") or []
    since: datetime | None = kwargs.get("since")
    scraped_at = datetime.now(timezone.utc)
    session = PoliteSession(min_delay=_MIN_DELAY, max_delay=_MAX_DELAY)
    seen: set[str] = set()
    postings: list[dict] = []

    for keyword in keywords:
        keyword_start = len(postings)
        try:
            items = _parse_feed(_fetch_feed(session, _feed_url(keyword)))
        except Exception as exc:  # noqa: BLE001 - a bad keyword never stops the others
            report(f"feed error (keyword={keyword!r}): {exc}")
            record_error("reliefweb", f"feed error (keyword={keyword!r}): {exc}")
            continue
        if not items:
            record_answered("reliefweb")
        for item in items:
            platform_id = item["platform_id"]
            if platform_id in seen or platform_id in known_ids:
                continue
            seen.add(platform_id)
            if since is not None and item["posted_at"] is not None and item["posted_at"] < since:
                continue
            postings.append(_to_posting(item, scraped_at))
        log_keyword_results("reliefweb", keyword, postings[keyword_start:])

    return sdk.keep_local(postings, config, "reliefweb")


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: the first keyword's feed, mapped without any filter. ``None`` when no keyword."""
    keywords = config.get("search_keywords") or config.get("role_targets") or []
    if not keywords:
        return None
    url = _feed_url(keywords[0])
    session = PoliteSession(min_delay=_MIN_DELAY, max_delay=_MAX_DELAY, timeout=PROBE_TIMEOUT_S, max_retries=0)

    def parse(text: str):
        items = _parse_feed(text)
        now = datetime.now(timezone.utc)
        return [_to_posting(i, now) for i in items], True, ""

    return run_probe(lambda: session.get(url).text, parse, "xml")
