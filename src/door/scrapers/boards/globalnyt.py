#!/usr/bin/env python3
"""Scraper for Globalnyt (globalnyt.dk), the Danish job board for international development and humanitarian work.

Endpoint: the WordPress REST list ``https://globalnyt.dk/wp-json/wp/v2/stilling?per_page=100`` (plain JSON, no
account). It holds every ad on the board (a few dozen at most, all in the sector), so the scraper returns them
all and leaves the title gate and the matcher to judge; the search keywords are not sent. A list item has the
id, date, link, title and the ad text, but not the employer or the place: for each new (not yet seen) ad the
scraper fetches the ad's page once and reads its labelled fields ``Organisation`` (the employer),
``Sted`` (the place, empty when the ad names none) from the page's text divs. An ad whose page cannot be
read keeps the board's name as its employer and the error is recorded.

Parsing (``_parse_list``, ``_detail_field``) is pure and tested from saved pages.

Terms: https://globalnyt.dk/ has no terms page that mentions automated access; the board is open and public.
robots.txt allows the REST route.
"""

import html as html_lib
import re
from datetime import datetime, timezone

from door.scrapers import sdk
from door.scrapers.sdk import (
    FEED_DELAY, JobPosting, PoliteSession, PROBE_TIMEOUT_S, ProbeResult, log_keyword_results, make_job_id, record_error,
    report, run_probe, strip_html,
)

_LIST_URL = "https://globalnyt.dk/wp-json/wp/v2/stilling?per_page=100"
_MIN_DELAY, _MAX_DELAY = FEED_DELAY

# Hosts of this board: a link here is an ad on the board, never an employer's own site (`ats_detect.is_job_board`).
JOB_BOARD_HOSTS = ("globalnyt.",)

# The employer of an ad whose page names none.
_BOARD_NAME = "Globalnyt"


def _parse_date(raw: str | None) -> datetime | None:
    parsed = sdk.parse_iso_date(raw)
    if parsed is not None and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_list(payload) -> list[dict]:
    """The ads of the WordPress list: ``platform_id``, ``title``, ``url``, ``posted_at``, ``description``.
    ValueError when the payload is not a list (a REST error is an object). Pure."""
    if not isinstance(payload, list):
        raise ValueError("not a list of ads")
    ads = []
    for node in payload:
        if not isinstance(node, dict) or not node.get("id") or not node.get("link"):
            continue
        ads.append({
            "platform_id": str(node["id"]),
            "title": html_lib.unescape(strip_html(str((node.get("title") or {}).get("rendered") or ""))).strip(),
            "url": str(node["link"]),
            "posted_at": _parse_date(node.get("date_gmt") or node.get("date")),
            "description": strip_html(str((node.get("content") or {}).get("rendered") or "")),
        })
    return ads


def _detail_field(page: str, label: str) -> str:
    """The value that follows the text div *label* on an ad's page (``Organisation`` -> "Røde Kors"); "" when absent. Pure."""
    match = re.search(r">\s*" + re.escape(label) + r"\s*</div>\s*<div[^>]*>\s*(.*?)\s*</div>", page, re.S)
    return html_lib.unescape(strip_html(match.group(1))).strip() if match else ""


def _to_posting(ad: dict, company: str, location: str, scraped_at: datetime) -> dict:
    posting = JobPosting(
        id=make_job_id("globalnyt", ad["platform_id"]),
        title=ad["title"],
        company=company or _BOARD_NAME,
        location=location,
        url=ad["url"],
        description=ad["description"],
        source="globalnyt",
        scraped_at=scraped_at,
        platform_id=ad["platform_id"],
        posted_at=ad["posted_at"],
    )
    return posting.model_dump(mode="json")


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Return JobPosting dicts for the ads of Globalnyt not seen before (and not older than ``since``)."""
    since: datetime | None = kwargs.get("since")
    scraped_at = datetime.now(timezone.utc)
    session = PoliteSession(min_delay=_MIN_DELAY, max_delay=_MAX_DELAY)
    try:
        ads = _parse_list(session.get(_LIST_URL).json())
    except Exception as exc:  # noqa: BLE001 - reported, never raised
        report(f"list error: {exc}")
        record_error("globalnyt", f"list error: {exc}")
        return []

    postings: list[dict] = []
    for ad in ads:
        if ad["platform_id"] in known_ids:
            continue
        if since is not None and ad["posted_at"] is not None and ad["posted_at"] < since:
            continue
        company = location = ""
        try:
            page = session.get(ad["url"]).text
            company, location = _detail_field(page, "Organisation"), _detail_field(page, "Sted")
        except Exception as exc:  # noqa: BLE001
            report(f"detail error ({ad['url']}): {exc}")
            record_error("globalnyt", f"detail error ({ad['url']}): {exc}")
        postings.append(_to_posting(ad, company, location, scraped_at))
    log_keyword_results("globalnyt", "all ads", postings)
    return postings


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: the list only, no detail pages. ``None`` for a profile with no keywords."""
    if not (config.get("search_keywords") or config.get("role_targets")):
        return None
    session = PoliteSession(min_delay=_MIN_DELAY, max_delay=_MAX_DELAY, timeout=PROBE_TIMEOUT_S, max_retries=0)

    def parse(text: str):
        import json
        ads = _parse_list(json.loads(text))
        now = datetime.now(timezone.utc)
        return [_to_posting(a, "", "", now) for a in ads], True, ""

    return run_probe(lambda: session.get(_LIST_URL).text, parse, "json")
