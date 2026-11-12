#!/usr/bin/env python3
"""Scraper for TeamTailor-hosted company career sites.

Uses each company's public, unauthenticated TeamTailor jobs feed.
Configured by ``teamtailor_companies`` in the profile config — a list of
company subdomain slugs, e.g. ``["storytel", "oatly"]`` (or career hosts, below).

API endpoint used:
  GET https://{company}.teamtailor.com/jobs.json
      → JSON Feed v1.1 (``{"title": ..., "items": [...]}``)
      Each item includes a ``content_html`` description and a ``_jobposting``
      schema.org JobPosting block (location, identifier) — no separate
      board-info or per-job detail call needed.

TeamTailor's ``robots.txt`` does not disallow ``/jobs.json``; like every
request, it is checked first (``PoliteSession``).

A ``teamtailor_companies`` entry is a subdomain slug (``templafy``) or a
company's own career host that points at Teamtailor (``careers.veo.co``).
``jobs.json`` answers every job on its first page today, but takes ``?page=N``,
so further pages are read until one adds no new job. When ``jobs.json`` fails,
``/jobs.rss`` — which Teamtailor documents as public — is the fallback.

Terms: https://www.teamtailor.com/en/terms-and-conditions/ — the feeds are
public. robots.txt disallows only its app and messaging paths, not the feeds.
"""

import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from xml.etree import ElementTree

from door.scrapers.sdk import (
    JobPosting, PoliteSession, PROBE_TIMEOUT_S, ProbeResult, host_of, make_job_id, tenant_platform_id, parse_iso_date, run_probe,
    scrape_feeds, strip_html, workers, followed_name,
)
from door.scrapers.sdk import keep_local
from door.scrapers.sdk import Detection, NOT_ACCOUNTS, Probe, parts

# The platform's own domains: a host on one is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("teamtailor.com",)

_MAX_PAGES = 20

_HEADERS = {
    "Accept": "application/json",
}
_RSS_HEADERS = {"Accept": "application/rss+xml, application/xml"}
_TT_NS = "https://teamtailor.com/locations"


def _location_text(item: dict) -> str:
    """Return a "; "-joined "City, CC" string from an item's jobLocation list.

    TeamTailor's schema.org ``jobLocation`` is a list of ``Place`` objects.
    ``addressRegion`` is deliberately ignored — it's inconsistent in real
    payloads (sometimes a country name, sometimes a city, sometimes None).
    """
    locations = (item.get("_jobposting") or {}).get("jobLocation") or []
    parts: list[str] = []
    for place in locations:
        address = (place or {}).get("address") or {}
        city = (address.get("addressLocality") or "").strip()
        country = (address.get("addressCountry") or "").strip()
        if city and country:
            parts.append(f"{city}, {country}")
        elif city or country:
            parts.append(city or country)
    return "; ".join(parts)


def _platform_id(item: dict) -> str:
    """Return the stable platform id for *item*.

    Prefers the numeric ``_jobposting.identifier.value`` (matches the id
    embedded in the item's URL, consistent with Greenhouse/Lever's
    numeric-id convention), falling back to the top-level UUID ``id``.
    """
    identifier = (item.get("_jobposting") or {}).get("identifier") or {}
    value = identifier.get("value")
    if value:
        return str(value)
    return str(item.get("id") or "")


def _feed_base(entry: str) -> str:
    """``https://<host>`` for a ``teamtailor_companies`` entry: a slug or a career host. Pure."""
    entry = entry.strip()
    if "." not in entry and "/" not in entry:
        return f"https://{entry.lower()}.teamtailor.com"
    parsed = urlparse(entry if "://" in entry else f"https://{entry}")
    return f"https://{parsed.netloc.lower()}"


def _fetch_board(session: PoliteSession, base: str) -> dict:
    """The JSON Feed for the board at *base*, every page of it.

    Returns ``{"title": ..., "items": [...]}`` with the items of all pages.
    Raises on HTTP errors or robots.txt disallow (of the first page).
    """
    first = session.get(f"{base}/jobs.json", headers=_HEADERS).json()
    items = list(first.get("items") or [])
    seen = {_platform_id(i) for i in items}
    for page in range(2, _MAX_PAGES + 1):
        if not items:
            break
        more = [i for i in session.get(f"{base}/jobs.json", headers=_HEADERS, params={"page": page}).json()
                .get("items") or [] if _platform_id(i) not in seen]
        if not more:
            break
        seen.update(_platform_id(i) for i in more)
        items.extend(more)
    return {**first, "items": items}


_RSS_ID_RE = re.compile(r"/jobs/(\d+)")


def _parse_rss(xml: str) -> tuple[str, list[dict]]:
    """``(company name, items)`` from a ``/jobs.rss`` feed; each item already has
    the posting fields (``platform_id``, ``title``, ``url``, ``location``,
    ``description``, ``posted_at``). Pure."""
    root = ElementTree.fromstring(xml)
    channel = root.find("channel")
    company = (channel.findtext("title") or "").strip() if channel is not None else ""
    items = []
    for node in root.iter("item"):
        url = (node.findtext("link") or "").strip()
        match = _RSS_ID_RE.search(url)
        places = []
        for loc in node.iter(f"{{{_TT_NS}}}location"):
            city = (loc.findtext(f"{{{_TT_NS}}}city") or "").strip()
            country = (loc.findtext(f"{{{_TT_NS}}}country") or "").strip()
            places.append(", ".join(p for p in (city, country) if p))
        try:
            posted = parsedate_to_datetime(node.findtext("pubDate") or "").isoformat()
        except (TypeError, ValueError):
            posted = None
        items.append({
            "platform_id": match.group(1) if match else (node.findtext("guid") or "").strip(),
            "title": (node.findtext("title") or "").strip(),
            "url": url,
            "location": "; ".join(p for p in places if p),
            "description": strip_html(node.findtext("description") or "", encoded=True),
            "posted_at": posted,
            "company": (node.findtext("company_name") or company).strip(),
        })
    return company, items


def _rss_posting(item: dict, scraped_at: datetime, name: str = "") -> dict:
    """Map one `_parse_rss` item to a JobPosting dict (the followed *name*, when given, wins)."""
    company = name or item["company"]
    platform_id = tenant_platform_id(item["url"], item["platform_id"])  # ids repeat across boards
    posting = JobPosting(
        id=make_job_id("teamtailor", platform_id),
        title=item["title"],
        company=company,
        location=item["location"],
        url=item["url"],
        description=item["description"],
        source="teamtailor",
        scraped_at=scraped_at,
        platform_id=platform_id,
        posted_at=parse_iso_date(item["posted_at"]),
        apply_type="external",
        apply_url=item["url"],
    )
    return posting.model_dump(mode="json")


def _to_posting(item: dict, company_name: str, scraped_at: datetime) -> dict:
    """Map one JSON Feed item to a JobPosting dict."""
    title = (item.get("title") or "").strip()
    url = item.get("url") or ""
    platform_id = tenant_platform_id(url, _platform_id(item))  # ids repeat across boards
    posting = JobPosting(
        id=make_job_id("teamtailor", platform_id),
        title=title,
        company=company_name,
        location=_location_text(item),
        url=url,
        description=strip_html(item.get("content_html") or "", encoded=True),
        source="teamtailor",
        scraped_at=scraped_at,
        platform_id=platform_id,
        posted_at=parse_iso_date(item.get("date_published")),
        apply_type="external",
        apply_url=url,
    )
    return posting.model_dump(mode="json")


def _board_postings(session: PoliteSession, slug: str, scraped_at: datetime, name: str = "") -> list[dict]:
    """One board's postings from its JSON Feed, else its RSS feed, labelled with the followed *name*
    when given. Raises the JSON Feed's error when both fail."""
    base = _feed_base(slug)
    try:
        data = _fetch_board(session, base)
        company_name = (name or data.get("title") or slug).strip()
        return [_to_posting(i, company_name, scraped_at) for i in data.get("items") or []]
    except Exception as exc:
        try:
            _, rss_items = _parse_rss(session.get(f"{base}/jobs.rss", headers=_RSS_HEADERS).text)
        except Exception:
            raise exc from None
        return [_rss_posting(i, scraped_at, name) for i in rss_items]


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Return a list of JobPosting-compatible dicts from configured TeamTailor boards."""
    # Boards on different hosts are fetched side by side (at most `PER_PROVIDER`
    # `*.teamtailor.com` boards at once).
    def fetch(session, slug, scraped_at):
        return _board_postings(session, slug, scraped_at, followed_name(config, "teamtailor_companies", slug))

    return keep_local(scrape_feeds("teamtailor", config.get("teamtailor_companies") or [], fetch,
                                   group=lambda slug: host_of(_feed_base(slug)), max_workers=workers(config),
                                   headers=_HEADERS), config, "teamtailor")


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: the first configured company. ``None`` when none is set."""
    companies: list[str] = config.get("teamtailor_companies", [])
    if not companies:
        return None
    slug = companies[0]
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)

    def fetch() -> str:
        return session.get(f"{_feed_base(slug)}/jobs.json", headers=_HEADERS).text

    def parse(text: str):
        data = json.loads(text)
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return [], False, "no `items` list in the JSON Feed"
        company_name = (data.get("title") or slug).strip()
        scraped_at = datetime.now(timezone.utc)
        return [_to_posting(i, company_name, scraped_at) for i in items
                if isinstance(i, dict) and _platform_id(i)], True, ""

    return run_probe(fetch, parse, "json")


# --- feed detection (issue #282): what `core/ats_detect.py` and `commands/companies.py` ask ---

FEED_KEY = "items"


def _host(entry: str) -> str:
    return entry if "." in entry else f"{entry}.teamtailor.com"


def detect_url(url: str) -> Detection | None:
    """A Teamtailor career site (``<account>.teamtailor.com``) and the account it names."""
    host, _path, _query = parts(url.strip())
    sub = host.split(".")[0]
    if host.endswith(".teamtailor.com") and host.count(".") == 2 and sub not in NOT_ACCOUNTS:
        return Detection("teamtailor", sub, f"Teamtailor career site {host}")
    return None


def feed_url(entry: str) -> str | None:
    """The feed that lists the jobs of *entry* (an account, or a career site on the employer's own host);
    a detection from page signatures is kept only when it lists jobs (under `FEED_KEY`)."""
    return "https://" + _host(entry) + "/jobs.json"


def name_probes(slug: str) -> list[Probe]:
    """The public feed to try for a company name's *slug*."""
    return [Probe(feed_url(slug), FEED_KEY, f"Teamtailor site {slug}")]


def detect_cname(host: str, target: str, where: str) -> Detection | None:
    """A career host that is a CNAME for Teamtailor's."""
    return Detection("teamtailor", host, where) if target == "ext.teamtailor.com" else None


def detect_html(html: str, url: str) -> Detection | None:
    """A career site on the employer's own host that loads Teamtailor's assets."""
    if "teamtailor-cdn.com" in html:
        return Detection("teamtailor", urlparse(url).netloc.lower(), f"{url} is a Teamtailor career site")
    return None
